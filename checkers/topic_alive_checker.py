"""
checkers/topic_alive_checker.py

Comprueba que llegue al menos un mensaje al topic durante la ejecución del bag.

El discovery del tipo de mensaje ocurre en background — _on_start() devuelve
inmediatamente sin bloquear, de forma que el bag puede arrancar mientras el
checker sigue buscando el topic en paralelo.

Uso en config.yaml:
    checkers:
      - type: TopicAliveChecker
        topic: /perception/map2

      - type: TopicAliveChecker
        topic: /slam/map2

      - type: TopicAliveChecker
        topic: /path_planning/trajectory2
"""

import time
import threading
import importlib
import math
import rclpy
import rclpy.executors
from rclpy.node import Node

from .base_checker import BaseChecker

_TOPIC_DISCOVERY_TIMEOUT  = 30.0   # segundos esperando a que aparezca el topic
_TOPIC_DISCOVERY_INTERVAL = 0.2


def _load_msg_class(type_str: str) -> type:
    """
    Convierte "nav_msgs/msg/OccupancyGrid" en la clase Python correspondiente.
    """
    parts = type_str.split("/")
    if len(parts) != 3:
        raise ValueError(f"Formato de tipo inesperado: '{type_str}'")
    pkg, _, cls_name = parts
    module = importlib.import_module(f"{pkg}.msg")
    return getattr(module, cls_name)


class TopicAliveChecker(BaseChecker):

    def __init__(self, topic: str, seconds: int, logger=None):
        super().__init__(name=f"TopicAliveChecker({topic})", logger=logger)

        self.topic          = topic
        self.seconds        = seconds
        self._received      = False
        self._last_msg_time = None  # Guardará el timestamp del último mensaje
        self._node          = None
        self._executor      = None
        self._spin_thread   = None
        self._setup_thread  = None
        self._timer         = None  # Referencia al timer de ROS2
    # ── Arranque ───────────────────────────────────────────────────────────

    def _on_start(self):
        """
        Devuelve inmediatamente. El discovery y la suscripción ocurren
        en _setup_thread de forma asíncrona mientras el bag arranca.
        """
        if not rclpy.ok():
            rclpy.init()

        node_name = "topic_alive_" + self.topic.replace("/", "_").strip("_")
        self._node = Node(node_name)

        # Executor + spin arranca ya para que el nodo esté activo
        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)

        self._spin_thread = threading.Thread(
            target=self._spin_safely,
            daemon=True,
            name=f"spin_{node_name}",
        )
        self._spin_thread.start()

        # Discovery en background — no bloquea _on_start()
        self._setup_thread = threading.Thread(
            target=self._discover_and_subscribe,
            daemon=True,
            name=f"setup_{node_name}",
        )
        self._setup_thread.start()

        self.logger.info(f"[{self.name}] iniciado — buscando '{self.topic}' en background...")

# ── Discovery + suscripción (corre en _setup_thread) ──────────────────

    def _discover_and_subscribe(self):
        deadline = time.time() + _TOPIC_DISCOVERY_TIMEOUT

        while time.time() < deadline:
            if not self._running:
                return 

            topics = dict(self._node.get_topic_names_and_types())
            if self.topic in topics:
                type_str = topics[self.topic][0]
                try:
                    msg_cls = _load_msg_class(type_str)
                except Exception as e:
                    self.logger.error(f"[{self.name}] Error cargando tipo '{type_str}': {e}")
                    self._record_failure(f"No se pudo cargar el tipo del topic '{self.topic}': {e}")
                    return

                # 1. Nos suscribimos
                self._node.create_subscription(
                    msg_cls,
                    self.topic,
                    self._callback,
                    10,
                )
                
                # 2. Creamos el Timer de ROS2 (el executor en background lo procesará)
                self._timer = self._node.create_timer(
                    self.seconds / 2.0,  # Comprobamos con mayor frecuencia que el límite
                    self._check_liveness
                )
                
                self.logger.info(
                    f"[{self.name}] suscrito a '{self.topic}' "
                    f"(tipo: {msg_cls.__name__})"
                )
                return

            time.sleep(_TOPIC_DISCOVERY_INTERVAL)

        # Si llegamos aquí, el topic nunca apareció
        self.logger.error(
            f"[{self.name}] '{self.topic}' no apareció en {_TOPIC_DISCOVERY_TIMEOUT}s"
        )
        self._record_failure(
            f"Topic '{self.topic}': no apareció en el grafo ROS2 "
            f"tras {_TOPIC_DISCOVERY_TIMEOUT}s."
        )
    def _spin_safely(self):
        try:
            self._executor.spin()
        except Exception:
            pass  # ExternalShutdownException al apagar, ignorar

    # ── Callback y Watchdog ───────────────────────────────────────────────

    def _callback(self, msg):
        """
        Se ejecuta cada vez que llega un mensaje. Actualiza el timestamp.
        """
        self._last_msg_time = time.time()
        
        if not self._received:
            self._received = True
            self.logger.info(
                f"[{self.name}] Primer mensaje recibido en '{self.topic}'. "
                f"Iniciando monitorización (timeout={self.seconds}s)."
            )

    def _check_liveness(self):
        """
        Llamado periódicamente por un Timer de ROS2. Comprueba si ha pasado
        demasiado tiempo desde el último mensaje recibido.
        """
        # Si aún no hemos recibido el primer mensaje o el checker se detuvo, ignoramos
        if not self._received or not self._running or self._last_msg_time is None:
            return

        elapsed = time.time() - self._last_msg_time
        if elapsed > self.seconds:
            self._record_failure(
                f"Silencio detectado en '{self.topic}': han pasado {elapsed:.2f}s "
                f"sin recibir mensajes (máximo permitido: {self.seconds}s)."
            )
            
            # Cancelamos el timer para no inundar el log con el mismo fallo una y otra vez
            if self._timer:
                self._timer.cancel()
    # ── Parada ────────────────────────────────────────────────────────────

    def _on_stop(self):
        # Esperar a que el setup thread termine (con límite)
        if self._setup_thread and self._setup_thread.is_alive():
            self._setup_thread.join(timeout=2.0)

        # Si el discovery terminó pero nunca llegó ningún mensaje
        if not self._received and not self._failures:
            self._record_failure(
                f"Topic '{self.topic}': no se recibió ningún mensaje durante el bag."
            )

        if self._executor:
            self._executor.shutdown(timeout_sec=2.0)
            self._executor = None

        if self._node:
            self._node.destroy_node()
            self._node = None

        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)

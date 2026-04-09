"""
checkers/position_received_checker.py

Comprueba que llegue al menos un mensaje al topic durante la ejecución del bag,
e imprime las coordenadas x e y de cada mensaje recibido.

Uso en config.yaml:
    checkers:
      - type: PositionReceivedChecker
        topic: /car_state/state2
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
    Convierte "common_msgs/msg/State" en la clase Python correspondiente.
    """
    parts = type_str.split("/")
    if len(parts) != 3:
        raise ValueError(f"Formato de tipo inesperado: '{type_str}'")
    pkg, _, cls_name = parts
    module = importlib.import_module(f"{pkg}.msg")
    return getattr(module, cls_name)


class PositionReceivedChecker(BaseChecker):

    def __init__(self, topic: str = "/car_state/state2", max_jump: float = 1.0, logger=None):
        super().__init__(name=f"PositionReceivedChecker({topic})", logger=logger)

        self.topic          = topic
        self.max_jump       = max_jump  # Límite máximo de salto permitido entre iteraciones
        
        self._received      = False
        self._prev_x        = None      # Guardará la posición X anterior
        self._prev_y        = None      # Guardará la posición Y anterior
        
        self._node          = None
        self._executor      = None
        self._spin_thread   = None
        self._setup_thread  = None
    # ── Arranque ───────────────────────────────────────────────────────────

    def _on_start(self):
        if not rclpy.ok():
            rclpy.init()

        node_name = "pos_checker_" + self.topic.replace("/", "_").strip("_")
        self._node = Node(node_name)

        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)

        self._spin_thread = threading.Thread(
            target=self._spin_safely,
            daemon=True,
            name=f"spin_{node_name}",
        )
        self._spin_thread.start()

        self._setup_thread = threading.Thread(
            target=self._discover_and_subscribe,
            daemon=True,
            name=f"setup_{node_name}",
        )
        self._setup_thread.start()

        self.logger.info(f"[{self.name}] iniciado — buscando '{self.topic}' en background...")

    # ── Discovery + suscripción ───────────────────────────────────────────

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

                self._node.create_subscription(
                    msg_cls,
                    self.topic,
                    self._callback,
                    10,
                )
                self.logger.info(f"[{self.name}] suscrito a '{self.topic}' (tipo: {msg_cls.__name__})")
                return

            time.sleep(_TOPIC_DISCOVERY_INTERVAL)

        self.logger.error(f"[{self.name}] '{self.topic}' no apareció en {_TOPIC_DISCOVERY_TIMEOUT}s")
        self._record_failure(f"Topic '{self.topic}': no apareció tras {_TOPIC_DISCOVERY_TIMEOUT}s.")

    def _spin_safely(self):
        try:
            self._executor.spin()
        except Exception:
            pass 

    # ── Callback ──────────────────────────────────────────────────────────

    def _callback(self, msg):
        """
        Se ejecuta cada vez que llega un mensaje. Comprueba que el salto
        de posición respecto al anterior no supere self.max_jump.
        """
        # Verificación de seguridad: comprobar que el mensaje tiene 'x' e 'y'
        if not (hasattr(msg, 'x') and hasattr(msg, 'y')):
            self._record_failure(f"Mensaje inválido en '{self.topic}': no tiene atributos 'x' e 'y'.")
            return

        # 1. El primer mensaje lo imprimimos entero y guardamos la posición inicial
        if not self._received:
            self._received = True
            self.logger.info(f"[{self.name}] Empezando a recibir mensajes en '{self.topic}'.")
            
            print("\n--- ESTRUCTURA COMPLETA DEL PRIMER MENSAJE ---")
            print(msg)
            print("----------------------------------------------\n")
            
            self._prev_x = msg.x
            self._prev_y = msg.y
            return
            
        # 2. Comprobar que el slam no vaya dando saltos
        curr_x = msg.x
        curr_y = msg.y

        # Calculamos la distancia euclídea entre el punto actual y el anterior
        jump = math.sqrt((curr_x - self._prev_x)**2 + (curr_y - self._prev_y)**2)

        # Si el salto supera el threshold, registramos el fallo
        if jump > self.max_jump:
            self._record_failure(
                f"SLAM bote detectado en '{self.topic}': "
                f"salto de {jump:.3f}m "
                f"({self._prev_x:.3f}, {self._prev_y:.3f}) → "
                f"({curr_x:.3f}, {curr_y:.3f}) "
                f"(máximo permitido: {self.max_jump}m)"
            )

        # 3. Actualizamos la posición anterior para la siguiente iteración
        self._prev_x = curr_x
        self._prev_y = curr_y

    # ── Parada ────────────────────────────────────────────────────────────

    def _on_stop(self):
        if self._setup_thread and self._setup_thread.is_alive():
            self._setup_thread.join(timeout=2.0)

        if not self._received and not self._failures:
            self._record_failure(f"Topic '{self.topic}': no se recibió ningún mensaje.")

        if self._executor:
            self._executor.shutdown(timeout_sec=2.0)
            self._executor = None

        if self._node:
            self._node.destroy_node()
            self._node = None

        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)

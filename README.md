# Rosbag Automation Testing

Sistema automático de testeo de rosbags desarrollado en Python sobre ROS2 Humble.

---

## Estructura del proyecto

```
rosbag_automation/
├── tester.py                        # Punto de entrada, bucle principal
├── config.yaml                      # Configuración del sistema
│
├── checkers/                        # Módulo de monitorización
│   ├── __init__.py                  # Registry + build_checkers()
│   ├── base_checker.py              # Clase abstracta base
│   ├── always_pass_checker.py       # Checker de prueba (siempre pasa)
│   ├── always_fail_checker.py       # Checker de prueba (siempre falla)
│   ├── topic_alive_checker.py       # Comprueba que un topic reciba mensajes cada N segundos
│   └── position_received_checker.py # Comprueba que el SLAM no dé botes
│
├── test_bags/                       # Rosbags pendientes de testear (.mcap)
├── failures/                        # Bags fallidos + reportes generados
└── logs/                            # Logs del tester con timestamp
```

---

## Despliegue

### Requisitos previos

- **ROS2 Humble** instalado y con el entorno cargado:
  ```bash
  source /opt/ros/humble/setup.bash
  source ~/ws/install/setup.bash   # tu workspace
  ```

- **Python 3.10+** (incluido con ROS2 Humble)

- **Dependencias Python:**
  ```bash
  pip install pyyaml
  ```
  El resto de dependencias (`rclpy`, `rclpy.executors`, etc.) vienen incluidas con ROS2.

- **Paquete ROS2 de mensajes** de tu sistema (`common_msgs` o el que uses) compilado en el workspace.

### Instalación

```bash
# 1. Clona o copia el proyecto en tu workspace
cd ~/ws
git clone <repo> rosbag_automation
cd rosbag_automation

# 2. Crea los directorios necesarios (se crean solos al arrancar, pero por si acaso)
mkdir -p test_bags failures logs

# 3. Ajusta el config
nano config.yaml
```

### Configuración mínima

Edita `config.yaml` antes de arrancar. Las secciones críticas son:

```yaml
rosbag_launch:
  package     : "common_meta"           # tu paquete ROS2
  launch_file : "rosbag_simulation.py"  # tu launch file

checkers:
  - type: TopicAliveChecker
    topic: /perception/map2
    seconds: 0.5
```

### Ejecución

```bash
# Coloca los .mcap en test_bags/
cp mis_bags/*.mcap test_bags/

# Arranca el tester
python3 tester.py

# Con config alternativa
python3 tester.py --config /ruta/a/otro_config.yaml
```

El tester corre en bucle infinito. Para pararlo: `Ctrl+C`.

---

## Cómo funciona

```
bucle infinito
│
├── escanea test_bags/ buscando .mcap
│
└── por cada bag:
        ├── ros2 launch <simulación>
        ├── ros2 bag play <bag.mcap>
        ├── checkers corriendo en paralelo (hilos)
        │
        ├── bag termina → stop() en cada checker
        │
        ├── PASS → siguiente bag
        └── FAIL → report_<bag>_<fecha>_at_<segundo>s.txt
                   bag movido a failures/
```

---

## Añadir un checker propio

### 1. La herencia

Todos los checkers heredan de `BaseChecker`. La clase base proporciona:

| Método/atributo | Qué hace |
|---|---|
| `start()` | Arranca el checker, inicializa el reloj interno, llama a `_on_start()` |
| `stop()` | Para el checker, llama a `_on_stop()` |
| `failures()` | Devuelve la lista de fallos como `[{"reason": str, "elapsed": float}]` |
| `_record_failure(reason)` | Registra un fallo con el segundo exacto en que ocurrió |
| `_running` | `True` mientras el checker está activo, `False` tras `stop()` |
| `_start_time` | Timestamp de cuando arrancó, para calcular el elapsed |
| `self.logger` | Logger configurado automáticamente con el nombre del checker |

Tú solo tienes que implementar **dos métodos**:

```
_on_start()  →  qué hace tu checker al arrancar
_on_stop()   →  qué hace al parar + comprobaciones finales
```

Y llamar a `_record_failure("descripción")` cuando detectes algo malo.

---

### 2. Molde

Copia esto en `checkers/mi_checker.py` y rellena los huecos:

```python
"""
checkers/mi_checker.py

Descripción de qué comprueba este checker.

Uso en config.yaml:
    checkers:
      - type: MiChecker
        topic: /mi/topic
        mi_parametro: 42.0
"""

import time
import threading

import rclpy
import rclpy.context
import rclpy.executors
from rclpy.node import Node

from .base_checker import BaseChecker

_TOPIC_DISCOVERY_TIMEOUT  = 30.0
_TOPIC_DISCOVERY_INTERVAL = 0.2


class MiChecker(BaseChecker):

    def __init__(self, topic: str, mi_parametro: float, logger=None):
        super().__init__(name=f"MiChecker({topic})", logger=logger)

        self.topic         = topic
        self.mi_parametro  = mi_parametro

        # Estado interno
        self._received     = False
        self._context      = None
        self._node         = None
        self._executor     = None
        self._spin_thread  = None
        self._setup_thread = None

    # ── Arranque ───────────────────────────────────────────────────────────

    def _on_start(self):
        # Contexto propio → aislado del resto de checkers y bags
        self._context = rclpy.context.Context()
        rclpy.init(context=self._context)

        node_name = "mi_checker_" + self.topic.replace("/", "_").strip("_")
        self._node = Node(node_name, context=self._context)

        self._executor = rclpy.executors.SingleThreadedExecutor(
            context=self._context
        )
        self._executor.add_node(self._node)

        self._spin_thread = threading.Thread(
            target=self._spin_safely,
            daemon=True,
        )
        self._spin_thread.start()

        self._setup_thread = threading.Thread(
            target=self._discover_and_subscribe,
            daemon=True,
        )
        self._setup_thread.start()

        self.logger.info(f"[{self.name}] iniciado")

    # ── Discovery (no tocar, igual en todos los checkers) ─────────────────

    def _discover_and_subscribe(self):
        import importlib
        deadline = time.time() + _TOPIC_DISCOVERY_TIMEOUT

        while time.time() < deadline:
            if not self._running:
                return
            try:
                topics = dict(self._node.get_topic_names_and_types())
            except Exception:
                return
            if self.topic in topics:
                type_str = topics[self.topic][0]
                parts    = type_str.split("/")
                module   = importlib.import_module(f"{parts[0]}.msg")
                msg_cls  = getattr(module, parts[2])
                self._node.create_subscription(msg_cls, self.topic, self._callback, 10)
                self.logger.info(f"[{self.name}] suscrito a '{self.topic}'")
                return
            time.sleep(_TOPIC_DISCOVERY_INTERVAL)

        self._record_failure(
            f"Topic '{self.topic}' no apareció en {_TOPIC_DISCOVERY_TIMEOUT}s."
        )

    def _spin_safely(self):
        try:
            self._executor.spin()
        except Exception:
            pass

    # ── Callback — AQUÍ va tu lógica ──────────────────────────────────────

    def _callback(self, msg):
        if not self._received:
            self._received = True

        # Ejemplo: accede a los campos del mensaje y comprueba lo que necesites
        # Si algo está mal → llama a _record_failure()
        #
        # valor = msg.mi_campo
        # if valor > self.mi_parametro:
        #     self._record_failure(f"Valor {valor} supera el límite {self.mi_parametro}")

    # ── Parada — comprobaciones finales ───────────────────────────────────

    def _on_stop(self):
        if self._setup_thread and self._setup_thread.is_alive():
            self._setup_thread.join(timeout=2.0)

        # Comprobar si nunca llegó ningún mensaje
        if not self._received and not self._failures:
            self._record_failure(
                f"Topic '{self.topic}': no se recibió ningún mensaje durante el bag."
            )

        # Aquí también puedes hacer comprobaciones sobre el estado acumulado
        # durante todo el bag, no solo por mensaje individual.

        if self._executor:
            self._executor.shutdown(timeout_sec=2.0)
            self._executor = None
        if self._node:
            self._node.destroy_node()
            self._node = None
        if self._context:
            self._context.shutdown()
            self._context = None
        if self._spin_thread and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=2.0)
```

---

### 3. Registrarlo en `__init__.py`

Abre `checkers/__init__.py` y añade dos líneas:

```python
# 1. Importa la clase
from .mi_checker import MiChecker

# 2. Añádela al registry
REGISTRY: dict[str, type[BaseChecker]] = {
    "AlwaysPassChecker"       : AlwaysPassChecker,
    "AlwaysFailChecker"       : AlwaysFailChecker,
    "TopicAliveChecker"       : TopicAliveChecker,
    "PositionReceivedChecker" : PositionReceivedChecker,
    "MiChecker"               : MiChecker,          # ← nueva línea
}
```

### 4. Configurarlo en `config.yaml`

```yaml
checkers:
  - type: MiChecker
    topic: /mi/topic
    mi_parametro: 42.0
```

Los parámetros del yaml (excepto `type`) se pasan automáticamente como `kwargs` al constructor. El nombre del parámetro en el yaml debe coincidir exactamente con el nombre del argumento en `__init__`.

---

## Reporte de fallos

Cuando un checker detecta un fallo, se genera automáticamente un fichero en `failures/`:

```
report_con_paralelizar_20260406_183012_at_47s.txt
              │                  │          │
           nombre del bag    fecha+hora  segundo del bag
                                         en que falló
```

Contenido del reporte:
```
============================================================
ROSBAG AUTOMATION TESTING — FAILURE REPORT
============================================================
Timestamp  : 2026-04-06T18:30:12
Bag file   : con_paralelizar.mcap
Failures   : 2
------------------------------------------------------------
  [1] @ 12.3s — Topic '/slam/map2': sin mensajes durante 21.4s
  [2] @ 47.1s — SLAM bote detectado: salto de 3.2m
============================================================
```

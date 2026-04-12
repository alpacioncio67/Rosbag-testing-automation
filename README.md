# Rosbag Automation Testing

Automatic rosbag testing system built in Python on top of ROS2 Humble.

---

## Project Structure

```
rosbag_automation/
├── tester.py                        # Entry point, main loop
├── config.yaml                      # System configuration
│
├── checkers/                        # Monitoring module
│   ├── __init__.py                  # Registry + build_checkers()
│   ├── base_checker.py              # Abstract base class
│   ├── always_pass_checker.py       # Test checker (always passes)
│   ├── always_fail_checker.py       # Test checker (always fails)
│   ├── topic_alive_checker.py       # Checks that a topic receives messages every N seconds
│   └── position_received_checker.py # Checks that SLAM does not produce position jumps
│
├── test_bags/                       # Rosbags pending testing (.mcap)
├── failures/                        # Failed bags + generated reports
└── logs/                            # Tester logs with timestamp
```

---

## Deployment

### Prerequisites

- **ROS2 Humble** installed with the environment sourced:
  ```bash
  source /opt/ros/humble/setup.bash
  source ~/ws/install/setup.bash   # your workspace
  ```

- **Python 3.10+** (included with ROS2 Humble)

- **Python dependencies:**
  ```bash
  pip install pyyaml
  ```
  The remaining dependencies (`rclpy`, `rclpy.executors`, etc.) are bundled with ROS2.

- **ROS2 message package** for your system (`common_msgs` or whichever you use) compiled in your workspace.

### Installation

```bash
# 1. Clone or copy the project into your workspace
cd ~/ws
git clone <repo> rosbag_automation
cd rosbag_automation

# 2. Create the required directories (auto-created on startup, but just in case)
mkdir -p test_bags failures logs

# 3. Edit the config
nano config.yaml
```

### Minimal Configuration

Edit `config.yaml` before starting. The critical sections are:

```yaml
rosbag_launch:
  package     : "common_meta"           # your ROS2 package
  launch_file : "rosbag_simulation.py"  # your launch file

checkers:
  - type: TopicAliveChecker
    topic: /perception/map2
    seconds: 0.5
```

### Running

```bash
# Place your .mcap files in test_bags/
cp my_bags/*.mcap test_bags/

# Start the tester
python3 tester.py

# With an alternative config
python3 tester.py --config /path/to/other_config.yaml
```

The tester runs in an infinite loop. To stop it: `Ctrl+C`.

---

## How It Works

```
infinite loop
│
├── scans test_bags/ for .mcap files
│
└── for each bag:
        ├── ros2 launch <simulation>
        ├── ros2 bag play <bag.mcap>
        ├── checkers running in parallel (threads)
        │
        ├── bag ends → stop() on each checker
        │
        ├── PASS → next bag
        └── FAIL → report_<bag>_<date>_at_<second>s.txt
                   bag moved to failures/
```

---

## Adding a Custom Checker

### 1. Inheritance

All checkers inherit from `BaseChecker`. The base class provides:

| Method / attribute | What it does |
|---|---|
| `start()` | Starts the checker, initialises the internal clock, calls `_on_start()` |
| `stop()` | Stops the checker, calls `_on_stop()` |
| `failures()` | Returns the list of failures as `[{"reason": str, "elapsed": float}]` |
| `_record_failure(reason)` | Records a failure with the exact second it occurred |
| `_running` | `True` while the checker is active, `False` after `stop()` |
| `_start_time` | Timestamp of when the checker started, used to compute elapsed time |
| `self.logger` | Logger automatically configured with the checker's name |

You only need to implement **two methods**:

```
_on_start()  →  what your checker does when it starts
_on_stop()   →  what it does when it stops + final checks
```

And call `_record_failure("description")` whenever something bad is detected.

---

### 2. Template

Copy this into `checkers/my_checker.py` and fill in the blanks:

```python
"""
checkers/my_checker.py

Description of what this checker verifies.

Usage in config.yaml:
    checkers:
      - type: MyChecker
        topic: /my/topic
        my_parameter: 42.0
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


class MyChecker(BaseChecker):

    def __init__(self, topic: str, my_parameter: float, logger=None):
        super().__init__(name=f"MyChecker({topic})", logger=logger)

        self.topic        = topic
        self.my_parameter = my_parameter

        # Internal state
        self._received    = False
        self._context     = None
        self._node        = None
        self._executor    = None
        self._spin_thread = None
        self._setup_thread = None

    # ── Startup ────────────────────────────────────────────────────────────

    def _on_start(self):
        # Own context → isolated from other checkers and bags
        self._context = rclpy.context.Context()
        rclpy.init(context=self._context)

        node_name = "my_checker_" + self.topic.replace("/", "_").strip("_")
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

        self.logger.info(f"[{self.name}] started")

    # ── Discovery (do not modify, same across all checkers) ───────────────

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
                self.logger.info(f"[{self.name}] subscribed to '{self.topic}'")
                return
            time.sleep(_TOPIC_DISCOVERY_INTERVAL)

        self._record_failure(
            f"Topic '{self.topic}' did not appear within {_TOPIC_DISCOVERY_TIMEOUT}s."
        )

    def _spin_safely(self):
        try:
            self._executor.spin()
        except Exception:
            pass

    # ── Callback — YOUR logic goes here ───────────────────────────────────

    def _callback(self, msg):
        if not self._received:
            self._received = True

        # Example: access message fields and check whatever you need.
        # If something is wrong → call _record_failure()
        #
        # value = msg.my_field
        # if value > self.my_parameter:
        #     self._record_failure(f"Value {value} exceeds limit {self.my_parameter}")

    # ── Shutdown — final checks ────────────────────────────────────────────

    def _on_stop(self):
        if self._setup_thread and self._setup_thread.is_alive():
            self._setup_thread.join(timeout=2.0)

        # Check whether any message was ever received
        if not self._received and not self._failures:
            self._record_failure(
                f"Topic '{self.topic}': no messages received during the bag."
            )

        # You can also perform checks on state accumulated across the entire
        # bag run here, not just per individual message.

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

### 3. Registering it in `__init__.py`

Open `checkers/__init__.py` and add two lines:

```python
# 1. Import the class
from .my_checker import MyChecker

# 2. Add it to the registry
REGISTRY: dict[str, type[BaseChecker]] = {
    "AlwaysPassChecker"       : AlwaysPassChecker,
    "AlwaysFailChecker"       : AlwaysFailChecker,
    "TopicAliveChecker"       : TopicAliveChecker,
    "PositionReceivedChecker" : PositionReceivedChecker,
    "MyChecker"               : MyChecker,          # ← new line
}
```

### 4. Configuring it in `config.yaml`

```yaml
checkers:
  - type: MyChecker
    topic: /my/topic
    my_parameter: 42.0
```

The yaml parameters (except `type`) are automatically passed as `kwargs` to the constructor. The parameter name in the yaml must match the argument name in `__init__` exactly.

---

## Failure Reports

When a checker detects a failure, a file is automatically generated in `failures/`:

```
report_con_paralelizar_20260406_183012_at_47s.txt
              │                  │          │
           bag name          date+time   second of the bag
                                          when it failed
```

Report contents:
```
============================================================
ROSBAG AUTOMATION TESTING — FAILURE REPORT
============================================================
Timestamp  : 2026-04-06T18:30:12
Bag file   : con_paralelizar.mcap
Failures   : 2
------------------------------------------------------------
  [1] @ 12.3s — Topic '/slam/map2': no messages for 21.4s
  [2] @ 47.1s — SLAM jump detected: position leap of 3.2m
============================================================
```

---

## 2.3 Uploading Data to Foxglove

We will not upload the original rosbags to Foxglove as received. Instead, we record a new bag on top of the simulation using `ros2 bag record`, and that recording is what gets uploaded.

### Execution Model

A new thread is added to the main program alongside the existing ones:

| Thread | Role |
|---|---|
| `ros2 launch common_meta rosbag_simulation_launch.py` | Starts the simulation |
| `ros2 bag play` | Replays the original bag |
| `ros2 bag record` | Records everything happening in parallel |
| Checker threads | Monitor topics in parallel |

### Flow

```
ros2 launch      →  starts the simulation
sleep 2s
ros2 bag play    →  replays the original bag
ros2 bag record  →  records all topics in parallel (--storage mcap)
checkers         →  monitor in parallel

bag play finishes
    │
    ├── SIGINT → record     ← stops the recording cleanly
    ├── stop() checkers
    │
    ├── PASS → shutil.rmtree(/tmp/rosbag_record_...)   ← recording discarded
    └── FAIL → shutil.move  → failures/recordings/recorded_<bag>_<timestamp>.mcap
                            → failures/metadata/metadata_<bag>_<timestamp>.yaml
                            → failures/reports/report_<bag>_<timestamp>.txt
                            → failures/<original_bag>.mcap
```

### `failures/` Directory Structure

```
failures/
  ├── recordings/    ← new recorded bags (only from failed runs)
  ├── metadata/      ← metadata.yaml from each failed recording
  ├── reports/       ← failure reports generated by checkers
  └── <original_bag>.mcap   ← original bags that failed
```

> The recording is only kept when the run fails. If the bag passes all checks, the temporary recording is deleted and nothing is stored.

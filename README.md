# ROSBAG Automation Testing

The goal of this system is to automate the testing of rosbags. The philosophy behind its development is **divide and conquer**: breaking the problem into subproblems and addressing them one by one. The system is designed to be as modular as possible to make future modifications and expansions straightforward.

---

## Table of Contents

1. [General System Overview](#1-general-system-overview)
2. [Detailed Implementation](#2-detailed-implementation)
   - [2.1 Base Program and Structure](#21-base-program-and-structure)
   - [2.2.1 Monitoring](#221-monitoring)
   - [2.2.2 Specific Checkers](#222-specific-checkers)

---

## 1. General System Overview

The system consists of four components:

- **Python script**
- **Configuration file**
- **Directory with rosbags** (`test_bags/`)
- **Failures directory**

The script loads the configuration file, checks the directory structure, and processes all rosbags in `test_bags/` in an infinite loop, executing them sequentially. Each rosbag is tested by simulating the manual workflow:

1. **Terminal 1:** `ros2 launch common_meta rosbag_simulation.py`
2. **Terminal 2:** `ros2 bag play rosbag.mcap`

During execution, the program monitors for specific failures using checker classes that act as ROS2 nodes subscribed to relevant topics. If a failure is detected, the program generates a report and moves the rosbag to the failures folder. In a future phase, it will also upload the rosbag to Foxglove.

---

## 2. Detailed Implementation

The implementation uses **rclpy** (ROS Client Library for Python), a Python wrapper over the `rcl` C library that allows the script to participate in the ROS2 ecosystem.

The development is structured in three major phases:

1. **Base program and structure** — Automating rosbag executions in an infinite loop.
2. **Monitoring ROS nodes and topics** — Checking conditions and handling failures.
3. **Foxglove integration** — Uploading failing rosbags to Foxglove *(future phase)*.

---

### 2.1 Base Program and Structure

The first goal is a Python program that imitates the manual rosbag simulation, without any checks.

#### Logging

The standard Python `logging` library is used instead of `print` statements. It provides message levels and types that give clear visibility into what the program is doing at each step.

#### Configuration File

The script loads a YAML configuration file to avoid hardcoding values. It covers:

- Directories
- Launch command (`ros2 launch common_meta rosbag_simulation_launch.py`)
- Rosbag play command
- Testing parameters: seconds to wait between launch and play, maximum time per bag, directory poll interval, etc.

#### Directory Setup

Using the `os` library, the script validates the directory structure and scans `test_bags/` for rosbags. A helper function to move a failing rosbag is also defined here (this will later become a Foxglove upload call).

#### `run_bag` Function

Handles the execution of a single rosbag. Using the loaded config dictionary, it runs the corresponding ROS2 commands to simulate the test. Returns `True` if the bag completes without failure, `False` otherwise.

#### Main Loop

`main_loop` runs the infinite loop that continuously polls `test_bags/`. It is called from `main`, the program's entry point.

**Main flow:**

```
1. Load configuration
2. Ensure directories exist
3. Execute the main loop
```

---

### 2.2.1 Monitoring

With the simulation running, the next step is implementing checks to detect failures.

#### Concepts

- **Node:** A process that participates in the ROS2 graph. It can publish, subscribe, offer services, etc. The tester itself must be a node to listen to what happens during playback.
- **Topic:** The communication channel. When a bag is played, it republishes messages to the same topics it recorded.
- **Callback:** A function registered on a subscription that executes automatically each time a new message arrives — this is where checks are performed.

#### The Threading Problem

ROS2 requires a `spin` loop to process callbacks — a blocking call that continuously listens on the network. Since the program already has its own blocking main loop, the ROS2 spin must run in a **separate thread**.

---

#### Checker Architecture

Each monitor is a class inheriting from `BaseChecker`, which defines the contract all checkers must fulfill:

```
BaseChecker
├── start()     → subscribe to the topic, start spin thread
├── stop()      → unsubscribe, stop thread
└── failures()  → return a list of strings with detected failures
```

Each specific checker only implements its own logic in the callback:

```
BaseChecker
    │
    ├── FrequencyChecker     ← Does the topic publish at the expected frequency?
    ├── TimeoutChecker       ← Does the topic stop publishing for more than N seconds?
    ├── ValueRangeChecker    ← Is a message field out of range?
    └── StampChecker         ← Do timestamps go backwards or jump?
```

The key design principle is that **each checker is completely independent** — it knows nothing about the rest of the system, simply listening to its topic and accumulating detected issues. This makes it easy to add new checker types without modifying existing code.

---

#### Integration into `run_bag`

```
run_bag()
│
├── 1. Instantiate checkers from config
│       checkers = [FrequencyChecker("/scan", min_hz=9.0),
│                   TimeoutChecker("/odom", max_gap_sec=1.0)]
│
├── 2. checker.start() for each one
│       → they subscribe and start their spin thread
│
├── 3. Launch proc_launch  (ros2 launch ...)
├── 4. Launch proc_play    (ros2 bag play ...)
│
├── 5. proc_play.wait()    ← blocks until the bag finishes
│       meanwhile, callbacks run in their threads
│
├── 6. checker.stop() for each one
│
└── 7. Collect results
        all_failures = []
        for checker in checkers:
            all_failures += checker.failures()

        return len(all_failures) == 0
```

---

#### Checker Configuration (`config.yaml`)

Checkers are defined in the config file rather than hardcoded:

```yaml
checkers:
  - type: FrequencyChecker
    topic: /scan
    min_hz: 9.0
    max_hz: 11.0

  - type: TimeoutChecker
    topic: /odom
    max_gap_seconds: 1.0

  - type: ValueRangeChecker
    topic: /diagnostics
    field: "level"
    min: 0
    max: 1
```

The script reads this list and dynamically instantiates each class with its parameters.

---

#### Basic Implementation & Validation

To verify the architecture, two test checkers are provided:

- `AlwaysPassChecker` — always returns no failures.
- `AlwaysFailChecker` — always returns a failure.

Running a batch of rosbags with these two checkers confirms that reports are generated correctly and that failing bags are moved to the failures folder as expected.

---

### 2.2.2 Specific Checkers

With the foundation in place, the actual checker logic can be implemented for the two main failure conditions:

1. **Check that key nodes are alive**
2. **Check that SLAM does not jump**

---

#### 1. SLAM Jump Checker (`slam_jump_checker.py`)

**Primary objective:** Guarantee the positional stability of the SLAM system by detecting anomalies, bounces, or abrupt teleportations between consecutive estimates.

**Implementation logic:**

1. Subscribes to the target topic (default: `/car_state/state2`) and intercepts each message.
2. Includes a safety barrier (`hasattr`) to ignore malformed messages without spatial coordinates.
3. Stores the coordinates of the previous message in internal state; the first message is skipped (no prior reference).
4. Calculates the Euclidean distance between the current and previous position using the Pythagorean theorem.
5. If the displacement exceeds `max_jump`, logs a failure with the coordinates and jump magnitude.

**Configuration example:**

```yaml
checkers:
  - type: PositionReceivedChecker
    topic: /car_state/state2
    max_jump: 1.0  # Maximum allowed displacement in meters between consecutive messages
```

---

#### 2. Topic Alive Checker (`topic_alive_checker.py`)

**Primary objective:** Act as a watchdog verifying the continuous vitality of a node or topic, ensuring messages flow at the expected frequency throughout the entire bag execution.

**Implementation logic:**

1. Delegates subscription and topic discovery to a background thread, preventing blockages during system initialization.
2. Implements a native ROS2 Timer linked to the executor, triggering at twice the allowed timeout frequency to avoid false positives.
3. On every message received, updates an absolute system timestamp.
4. The timer periodically checks the elapsed time since the last message. If it exceeds the configured threshold, a flow drop is declared, the failure is logged, and the recurring alert is cancelled to keep logs clean.

**Configuration example:**

```yaml
checkers:
  - type: TopicAliveChecker
    topic: /perception/map2
    seconds: 2  # Maximum seconds allowed without receiving a message
  - type: TopicAliveChecker
    topic: /path_planning/trajectory2
    seconds: 5
```

---

#### Checker Startup Internals

**Phase 1 — Isolated context:**

```python
self._context = rclpy.context.Context()
rclpy.init(context=self._context)
```

Each checker creates its own `rclpy` context instead of using the global one. This is critical: it prevents the global context from being invalidated when a bag finishes and its checkers are torn down.

**Phase 2 — Background topic discovery:**

```
loop every 0.2s for up to 30s
│
├── node.get_topic_names_and_types()
│       returns all active topics in the ROS2 graph
│       e.g. {"/perception/map2": ["nav_msgs/msg/OccupancyGrid"], ...}
│
├── Is our topic present?
│       NO  → wait 0.2s and retry
│       YES → extract type: "nav_msgs/msg/OccupancyGrid"
│               │
│               └── _load_msg_class()
│                       split by "/" → pkg="nav_msgs", cls="OccupancyGrid"
│                       importlib.import_module("nav_msgs.msg")
│                       getattr(module, "OccupancyGrid")
│                       returns the real Python class
│
└── create_subscription(msg_cls, topic, _callback, 10)
        executor now delivers messages to _callback
```

**Phase 3 — Message reception (`_callback`):**

The callback receives each message and applies the checker-specific logic. For the alive checker, it verifies that messages arrive within the configured time window by comparing timestamps between consecutive messages.

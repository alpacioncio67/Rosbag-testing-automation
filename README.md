# ROSBAG AUTOMATION TESTING

To improve our testing process, I am going to develop an automated rosbag testing system. The system will be developed in Python.

The philosophy I will follow to develop this system is "divide and conquer." I am going to break down everything we want to tackle into subproblems so they can be addressed one by one. Additionally, I will create a GitHub repository to deploy this with a simple `git clone`. The documentation approach will be more oriented towards the problems I encounter as I tackle each part of the system individually.

Another thing to note is that I will try to modularize the system as much as possible to make it easier to implement modifications or extensions in the future.

## Table of Contents

1. General System Overview
2. Detailed Implementation

---

## 1. OVERVIEW

The system consists of:

* A Python script
* A configuration file
* A rosbags directory
* A failures directory

The script will load the configuration file, check the directory structure, and process all the rosbags in the `test_bags` folder in an infinite loop. The bags will be executed sequentially. To achieve this, the program simulates the individual testing of a rosbag using:

* One terminal running: `rosbag launch common_meta rosbag_simulation.py`
* Another terminal running: `rosbag play rosbag.mcap`

During the execution of each rosbag, the program will actively monitor for specific failures. We will accomplish this using classes acting as ROS nodes that will subscribe to certain nodes and perform checks (more detail in section 2).

The goal is that if the program detects a failure, it generates a failure report, removes the rosbag from the testing folder, and uploads it to Foxglove. However, I have created a local "failures" directory because, during the early stages of development, the script will simply generate the report and move the failed rosbag to this folder. Later, once everything runs smoothly locally, I will implement the Foxglove upload functionality.

---

## 2. Detailed Implementation

The implementation will consist of 3 main phases:

* **Base program and structure:** Making our program capable of automating rosbag executions infinitely.
* **Monitoring:** Tracking ROS nodes and topics to run checks, and moving the rosbag in case of a failure.
* **Foxglove Integration:** Adding the functionality to upload a rosbag to Foxglove in case of a failure.

### 2.1 Base Program and Structure

The first thing we want to build is a Python program that mimics the manual simulation of rosbags, without running any checks initially.

* **Logging Setup:** The first step is to configure logging. This is basically a Python library that allows us to output execution messages for our program, rather than purely using `print` statements. It features levels and message types that will help us better monitor what is happening inside our program.

* **Configuration File:** The script loads the configuration file to avoid hardcoding values and touching the source code in the future. It includes:
  * Directory paths
  * Launch command (`rosbag launch common_meta rosbag_simulation_launch.py`)
  * Rosbag play command
  * Testing parameters: Wait time (in seconds) between launch and play, maximum time per bag, wait time before re-checking the directory, etc.

Once the configuration is loaded, and making use of the `os` library, the script verifies the directory structure and looks for rosbags inside the `test_bags` directory. The function responsible for moving a rosbag in case of a failure is also defined here (eventually, once the script is well-defined, this function will handle the Foxglove upload).

* **`run_bag` Function:** Once the script selects a rosbag to test, this function takes over. Using a dictionary (`config`), it executes the corresponding ROS commands to simulate the individual testing of that rosbag. This function will return a boolean: it will return `True` if the bag finishes without any failures (keeping in mind we aren't monitoring anything yet), and `False` otherwise.

* **`main_loop` Function:** Finally, we have the `main_loop` function, which creates the infinite loop that constantly checks the `test_bags` directory. This function is called from `main`, which acts as the entry point of the program.

**Main Execution Flow:**
1. Load configuration.
2. Ensure directories exist.
3. Execute the main loop.

### 2.2.1 Monitoring

Now that we have the testing simulation in place, we need to get our Python script to perform checks until it finds what we consider a failure. Specifically, we want to implement checks to:

* Ensure nodes do not die.
* Ensure the SLAM does not jump/bounce around.

**Nodes:**
A node is simply a process that participates in the ROS2 graph. It can publish, subscribe, offer services, etc. In our case, the tester needs to be a node itself to be able to "listen" to what happens during playback.

**Topics:**
This is the communication channel. When a bag is played back, it publishes messages to the same topics it recorded. 

A node (in this case, our program) subscribes to a topic and registers a *callback*, which is a function that executes automatically every time a new message arrives (this is where we will perform the checks).

* **The Threading Problem:**
ROS2 requires a `spin` to process callbacks (a blocking loop that continuously listens to the network). Because of this, we must run the ROS2 spin in a separate thread, since our program already has its own blocking main loop (which is infinite).

* **Checkers Architecture:**
Each monitor will be a class that inherits from `BaseChecker`, a class that defines the contract all checkers must fulfill.

```text
BaseChecker
├── start()        → subscribe to topic, start spin thread
├── stop()         → unsubscribe, stop thread
└── failures()     → return list of strings with detected failures
```

Each specific checker only has to implement its checking logic in the callback:
```
BaseChecker
    │
    ├── FrequencyChecker     ← Does the topic publish at the expected frequency?
    ├── TimeoutChecker       ← Does the topic stop publishing for more than N seconds?
    ├── ValueRangeChecker    ← Is a message field out of range?
    └── StampChecker         ← Do timestamps go backwards or jump?
```
Integration into run_bag:

The complete flow of our run_bag function with monitoring added would look like this:

run_bag()
│
├── 1. Instantiate checkers based on config
│       checkers = [FrequencyChecker("/scan", min_hz=9.0),
│                   TimeoutChecker("/odom", max_gap_sec=1.0)]
│
├── 2. checker.start() for each one
│       → they subscribe and start their spin thread
│
├── 3. Launch proc_launch  (ros2 launch ...)
├── 4. Launch proc_play    (ros2 bag play ...)
│
├── 5. proc_play.wait()    ← blocking until the bag finishes
│       meanwhile, callbacks run in their separate threads
│
├── 6. checker.stop() for each one
│
└── 7. Collect results
        all_failures = []
        for checker in checkers:
            all_failures += checker.failures()

        return len(all_failures) == 0

Checker Configuration in config.yaml:
Instead of hardcoding the checkers into the code, they are defined in the config file.
```
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
The script reads the list and dynamically instantiates each class with its parameters, adding them to a list of checkers.

The key to this design is that each checker is completely independent; it knows nothing about the rest of the system. It simply listens to its topic and accumulates whatever it finds to be wrong. This makes it incredibly easy to add new types of configurations without touching the existing code. We just need to modify the config.yaml to specify which checkers we want to use.

    Basic Implementation:
    To verify and validate that this system works, we will create the BaseChecker and its derived classes in a separate folder to keep everything modular and structured. Then, we will create one checker that always returns True and another that always returns False, to test the logic I just developed.

I recommend taking a look at the base_checker class to understand the structure behind it, and to easily see how each inherited class only has to implement its specific logic.

We must make several changes to run_bag, main, and write_report. To handle the failure logic, we will store a list of failures that we will process to create the report. If this list is empty, the test is considered valid and the bag remains where it is.

System Validation up to this point:

To verify that the system is on the right track, I am going to run a test with several rosbags. For this purpose, and available in the repository, I will be using two dummy checkers: one that always passes and another that always fails.

By doing this, we can verify that the corresponding reports are created and the bags are successfully moved to the failures folder (later, this would trigger an upload to Foxglove).

2.2.2 Specific Checkers

Now that we have the foundations of the system solidly in place, we must build the unique logic for each specific checker we want to create.

   - Check that the nodes we want to monitor are alive.

   - Check that the SLAM doesn't jump.

   - check_nodos_vivos (Check Live Nodes):
   - 
    To verify if the nodes are alive, we will subscribe to the corresponding topics and check if we are receiving messages when we are supposed to. The topics we are going to monitor are:

        /perception/map2

        /slam/map2

        /path_planning/trajectory2

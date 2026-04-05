# ROSBAG AUTOMATION TESTING

To improve our testing process, I am going to develop an automated rosbag testing system. The system will be developed in Python.

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

During the execution of each rosbag, the program will actively monitor for specific failures. We will accomplish this using classes acting as ROS nodes that will subscribe to certain nodes/topics and perform checks (more detail in section 2).

The goal is that if the program detects a failure, it will generate a failure report, remove the rosbag from the testing folder, and upload it to Foxglove. However, I have created a local "failures" directory because, during the early stages of development, the script will simply generate the report and move the failed rosbag to this folder. Later, once everything runs smoothly locally, I will implement the Foxglove upload functionality.

---

## 2. Detailed Implementation

### 2.1 Base Program and Structure

The first thing we want to build is a Python program that mimics the manual simulation of rosbags, without running any checks initially.

* **Logging Setup:** The first step is to configure logging. This is a standard Python library that allows us to output execution messages with specific levels and types (e.g., info, warning, error), rather than just using basic `print` statements. This will help us better monitor what is happening inside our program.

* **Configuration File:** The script loads the configuration file to avoid hardcoding values and touching the source code in the future. It will include:
    * Directory paths
    * Launch command (`rosbag launch common_meta rosbag_simulation_launch.py`)
    * Rosbag play command
    * Testing parameters: Wait time (in seconds) between launch and play, maximum time per bag, wait time before re-checking the directory, etc.

* **Directory Management:** Once the configuration is loaded, the script uses the `os` library to verify the directory structure and look for rosbags inside the `test_bags` directory. The function responsible for moving a rosbag in case of a failure is also defined here (eventually, once the script is finalized, this function will handle the Foxglove upload).

* **`run_bag` Function:** Once the script selects a rosbag to test, this function takes over. Using a dictionary (`config`), it executes the corresponding ROS commands to simulate the individual testing of that rosbag. This function returns a boolean: it returns `True` if the bag finishes without any crashes/failures (keeping in mind we aren't actively monitoring for logic errors yet), and `False` otherwise.

* **`main_loop` Function:** Finally, we have the `main_loop` function, which creates the infinite loop that constantly checks the `test_bags` directory. This function is called from `main`, which acts as the entry point of the program.

**Main Execution Flow:**
1. Load configuration.
2. Ensure directories exist.
3. Execute the main loop.

### 2.2 Monitoring
*(To be developed)*

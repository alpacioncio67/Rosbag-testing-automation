#!/usr/bin/env python3
"""
ROSBAG AUTOMATION TESTING
Sistema automático de testeo de rosbags.
"""

import os
import sys
import time
import shutil
import signal
import subprocess
import logging
from datetime import datetime
from pathlib import Path

import yaml

from checkers import build_checkers


# ──────────────────────────────────────────────
#  Logging setup
# ──────────────────────────────────────────────
def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"tester_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("rosbag_tester")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


# ──────────────────────────────────────────────
#  Config loader
# ──────────────────────────────────────────────
def load_config(config_path: str) -> dict:
    """Load and validate the YAML configuration file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r") as f:
        config = yaml.safe_load(f)

    required_keys = ["directories", "rosbag_play", "rosbag_launch", "testing"]
    for key in required_keys:
        if key not in config:
            raise KeyError(f"Missing required config section: '{key}'")

    return config


# ──────────────────────────────────────────────
#  Directory structure check
# ──────────────────────────────────────────────
def ensure_directories(config: dict, logger: logging.Logger) -> dict:
    """Ensure all required directories exist, create them if missing."""
    dirs = {}
    for name, path_str in config["directories"].items():
        p = Path(path_str).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        dirs[name] = p
        logger.debug(f"Directory OK: [{name}] → {p}")

    logger.info("Directory structure verified.")
    return dirs


# ──────────────────────────────────────────────
#  Rosbag discovery
# ──────────────────────────────────────────────
def get_rosbags(test_bags_dir: Path) -> list[Path]:
    """Return a sorted list of .mcap files in the test_bags directory."""
    bags = sorted(test_bags_dir.glob("*.mcap"))
    return bags


def write_report(bag_path: Path, failures_dir: Path, failures: list, logger: logging.Logger):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Normalizar — acepta tanto dicts {"reason":..., "elapsed":...} como strings
    normalized = []
    for f in failures:
        if isinstance(f, dict):
            normalized.append(f)
        else:
            normalized.append({"reason": str(f), "elapsed": 0.0})

    first_elapsed = int(normalized[0]["elapsed"]) if normalized else 0
    report_name = f"report_{bag_path.stem}_{timestamp}_at_{first_elapsed}s.txt"
    report_path = failures_dir / report_name

    lines = [
        "=" * 60,
        "ROSBAG AUTOMATION TESTING — FAILURE REPORT",
        "=" * 60,
        f"Timestamp  : {datetime.now().isoformat()}",
        f"Bag file   : {bag_path.name}",
        f"Failures   : {len(normalized)}",
        "-" * 60,
    ]
    for i, f in enumerate(normalized, 1):
        elapsed_str = f"{f['elapsed']:.1f}s"
        lines.append(f"  [{i}] @ {elapsed_str} — {f['reason']}")
    lines.append("=" * 60)

    report_path.write_text("\n".join(lines) + "\n")
    logger.info(f"Report written → {report_path}")
    return report_path

# ──────────────────────────────────────────────
#  Move bag to failures
# ──────────────────────────────────────────────
def move_to_failures(bag_path: Path, failures_dir: Path, logger: logging.Logger):
    dest = failures_dir / bag_path.name
    # Avoid overwriting if a bag with the same name already failed before
    if dest.exists():
        stem = bag_path.stem
        suffix = bag_path.suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = failures_dir / f"{stem}_{timestamp}{suffix}"

    shutil.move(str(bag_path), str(dest))
    logger.warning(f"Bag moved to failures → {dest}")


# ──────────────────────────────────────────────
#  Single bag simulation
# ──────────────────────────────────────────────
def run_bag(bag_path: Path, config: dict, logger: logging.Logger) -> tuple[bool, list[str]]:
    """
    Simulate testing of a single rosbag.

    Returns (True, []) si no hay fallos,
            (False, [lista de fallos]) si algún checker detecta algo.
    """
    launch_cfg   = config["rosbag_launch"]
    play_cfg     = config["rosbag_play"]
    test_cfg     = config["testing"]
    checker_cfgs = config.get("checkers", [])

    launch_cmd = [
        "ros2", "launch",
        launch_cfg["package"],
        launch_cfg["launch_file"],
    ] + launch_cfg.get("extra_args", [])

    play_cmd = [
        "ros2", "bag", "play",
        str(bag_path),
    ] + play_cfg.get("extra_args", [])

    logger.info(f"  Launch cmd : {' '.join(launch_cmd)}")
    logger.info(f"  Play cmd   : {' '.join(play_cmd)}")

    # ── Instanciar checkers ────────────────────────────────────
    checkers = build_checkers(checker_cfgs, logger)
    logger.info(f"  Checkers   : {[c.name for c in checkers] or 'none'}")

    proc_launch = None
    proc_play   = None

    def collect_failures() -> list[str]:
        all_failures = []
        for checker in checkers:
            checker.stop()
            all_failures.extend(checker.failures())
        return all_failures

    try:
        # ── Start simulation node ──────────────────────────────
        proc_launch = subprocess.Popen(
            launch_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.debug(f"  Launch PID : {proc_launch.pid}")

        time.sleep(test_cfg.get("launch_settle_seconds", 2.0))

        # ── Start bag playback ─────────────────────────────────
        proc_play = subprocess.Popen(
            play_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.debug(f"  Play PID   : {proc_play.pid}")

        # ── Arrancar checkers DESPUÉS del play ─────────────────
        # Los topics ya están publicándose en el grafo ROS2
        # en este punto, así que el discovery funciona correctamente
        for checker in checkers:
            checker.start()

        # ── Wait for playback to finish ────────────────────────
        timeout = test_cfg.get("play_timeout_seconds", None)
        proc_play.wait(timeout=timeout)
        logger.debug(f"  Play finished with returncode={proc_play.returncode}")

        failures = collect_failures()
        return (len(failures) == 0, failures)

    except subprocess.TimeoutExpired:
        logger.error("  Playback exceeded timeout — treating as failure.")
        failures = collect_failures()
        failures.insert(0, "Playback exceeded configured timeout.")
        return (False, failures)

    except FileNotFoundError as exc:
        logger.warning(f"  ROS2 binary not found ({exc}). Simulating dry-run.")
        time.sleep(test_cfg.get("dry_run_sleep_seconds", 1.0))
        failures = collect_failures()
        return (len(failures) == 0, failures)

    finally:
        for proc, name in [(proc_play, "play"), (proc_launch, "launch")]:
            if proc and proc.poll() is None:
                logger.debug(f"  Terminating {name} process (PID {proc.pid})")
                proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


# ──────────────────────────────────────────────
#  Main loop
# ──────────────────────────────────────────────
def main_loop(config: dict, dirs: dict, logger: logging.Logger):
    test_bags_dir = dirs["test_bags"]
    failures_dir  = dirs["failures"]
    cycle         = 0

    logger.info("=" * 60)
    logger.info("  ROSBAG AUTOMATION TESTING — starting infinite loop")
    logger.info("  Press Ctrl+C to stop.")
    logger.info("=" * 60)

    try:
        while True:
            cycle += 1
            bags = get_rosbags(test_bags_dir)

            if not bags:
                logger.info(f"[Cycle {cycle}] No .mcap files found in {test_bags_dir}. Waiting...")
                time.sleep(config["testing"].get("empty_dir_wait_seconds", 10))
                continue

            logger.info(f"[Cycle {cycle}] Found {len(bags)} bag(s) to process.")

            for bag_path in bags:
                logger.info(f"  ▶ Processing: {bag_path.name}")

                success, failures = run_bag(bag_path, config, logger)

                if success:
                    logger.info(f"  ✔ PASSED — {bag_path.name}")
                else:
                    logger.warning(f"  ✖ FAILED  — {bag_path.name}")
                    write_report(
                        bag_path=bag_path,
                        failures_dir=failures_dir,
                        failures=failures,
                        logger=logger,
                    )
                    move_to_failures(bag_path, failures_dir, logger)

            logger.info(f"[Cycle {cycle}] All bags processed. Restarting cycle...\n")

    except KeyboardInterrupt:
        logger.info("Interrupted by user. Shutting down.")


# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rosbag Automation Tester")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML configuration file (default: config.yaml)",
    )
    args = parser.parse_args()

    # 1. Load config
    try:
        cfg = load_config(args.config)
    except (FileNotFoundError, KeyError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # 2. Ensure directories
    log_dir = Path(cfg["directories"].get("logs", "logs"))
    logger  = setup_logging(log_dir)
    dirs    = ensure_directories(cfg, logger)

    # 3. Run
    main_loop(cfg, dirs, logger)

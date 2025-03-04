#!/usr/bin/env python3
"""
Utility to clean up lock files and terminate stray processes
"""
import os
import sys
import glob
import logging
import signal
import subprocess
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def get_bot_processes():
    """Get list of python processes running the bot"""
    try:
        result = subprocess.run(
            ["ps", "-ef"], 
            capture_output=True, 
            text=True, 
            check=True
        )

        processes = []
        for line in result.stdout.splitlines():
            if "python" in line and ("bot.py" in line or "run_bot.py" in line):
                # Skip the grep process itself and this script
                if "clean_locks.py" not in line:
                    processes.append(line.split()[1])  # Get PID

        return processes
    except Exception as e:
        logger.error(f"Error getting bot processes: {e}")
        return []

def terminate_processes(pids):
    """Terminate list of processes by PID"""
    for pid in pids:
        try:
            logger.info(f"Terminating process {pid}")
            os.kill(int(pid), signal.SIGTERM)
            # Give it a moment to terminate gracefully
            time.sleep(0.5)

            # Check if process is still running
            try:
                os.kill(int(pid), 0)  # Signal 0 is used to check if process exists
                logger.warning(f"Process {pid} still running, forcing kill")
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                # Process already terminated
                pass

        except ProcessLookupError:
            logger.info(f"Process {pid} not found")
        except Exception as e:
            logger.error(f"Error terminating process {pid}: {e}")

def remove_lock_files():
    """Remove all lock files in the current directory"""
    try:
        lock_files = glob.glob("*.lock")
        if lock_files:
            logger.info(f"Removed lock files matching: {', '.join(lock_files)}")
            for lock_file in lock_files:
                try:
                    os.remove(lock_file)
                except Exception as e:
                    logger.error(f"Error removing lock file {lock_file}: {e}")
        else:
            logger.info("No lock files found")
    except Exception as e:
        logger.error(f"Error removing lock files: {e}")

def main():
    """Main function to clean up lock files and processes"""
    logger.info("🧹 Starting cleanup...")

    logger.info("Checking for lock files...")

    # Terminate existing bot processes
    logger.info("Terminating any existing bot processes...")
    bot_pids = get_bot_processes()
    if bot_pids:
        logger.info(f"Found {len(bot_pids)} bot processes: {', '.join(bot_pids)}")
        terminate_processes(bot_pids)
    else:
        logger.info("No bot processes found")

    # Remove all lock files
    logger.info("Removing any Telegram bot lock files...")
    remove_lock_files()

    logger.info("✅ Cleanup completed")
    return 0

if __name__ == "__main__":
    sys.exit(main())

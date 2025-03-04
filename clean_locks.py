#!/usr/bin/env python3
"""
Clean up any existing bot processes and lock files
"""
import os
import sys
import logging
import subprocess
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def cleanup():
    """Clean up any existing bot processes and lock files"""
    try:
        # Kill any running bot processes
        logger.info("Terminating any existing bot processes...")
        commands = [
            "pkill -f 'python.*bot.py' || true",
            "pkill -f 'telebot' || true",
            "rm -f *.lock || true",
            "rm -f *.pid || true"
        ]

        for cmd in commands:
            subprocess.run(cmd, shell=True, check=False)

        # Give processes time to terminate
        time.sleep(2)

        # Check if any bot processes are still running
        ps_check = subprocess.run(
            "ps aux | grep 'python.*bot.py' | grep -v grep || true", 
            shell=True, 
            capture_output=True, 
            text=True
        )

        if ps_check.stdout.strip():
            logger.warning("Some bot processes are still running. Attempting force kill...")
            subprocess.run("pkill -9 -f 'python.*bot.py' || true", shell=True, check=False)
            time.sleep(1)

        # Verify all processes are terminated
        final_check = subprocess.run(
            "ps aux | grep 'python.*bot.py' | grep -v grep | wc -l", 
            shell=True, 
            capture_output=True, 
            text=True
        )

        if int(final_check.stdout.strip()) == 0:
            logger.info("All bot processes successfully terminated")
        else:
            logger.warning(f"Warning: {final_check.stdout.strip()} bot processes still running")

        return True
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting cleanup...")
    success = cleanup()
    logger.info(f"Cleanup {'successful' if success else 'failed'}")
    sys.exit(0 if success else 1)

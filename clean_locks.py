#!/usr/bin/env python3
"""
Enhanced cleanup script to remove lock files and terminate stray processes
"""
import os
import signal
import logging
import sys
import psutil
import time
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def find_bot_processes():
    """Find all Python processes related to the bot"""
    bot_processes = []

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Check if this is a Python process
            if proc.info['name'] == 'python' or proc.info['name'] == 'python3':
                cmdline = proc.info['cmdline'] if proc.info['cmdline'] else []

                # Look for bot-related Python scripts
                if any(script in ' '.join(cmdline) for script in ['bot.py', 'run_bot.py']):
                    bot_processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            continue

    return bot_processes

def kill_process_tree(pid, sig=signal.SIGTERM):
    """Kill a process and all its children"""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)

        # Send signal to parent
        parent.send_signal(sig)

        # Send signal to children
        for child in children:
            try:
                child.send_signal(sig)
            except psutil.NoSuchProcess:
                pass

        # Wait for processes to terminate
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)

        # Force kill if still alive
        if alive:
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass

        return len(gone) + len(alive)
    except psutil.NoSuchProcess:
        return 0

def cleanup(force=False):
    """Remove lock files and kill stray bot processes"""
    logger.info("🧹 Running cleanup script...")

    # First check for lock files
    logger.info("Checking for lock files...")
    lock_files = ["bot_runner.lock", "database_connections.lock"]
    for lock_file in lock_files:
        if os.path.exists(lock_file):
            logger.info(f"Found lock file: {lock_file}")

    # Kill any existing bot processes
    logger.info("Terminating any existing bot processes...")
    bot_processes = find_bot_processes()

    if bot_processes:
        logger.info(f"Found {len(bot_processes)} bot-related processes")

        for proc in bot_processes:
            try:
                pid = proc.info['pid']
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else 'Unknown'
                logger.info(f"Terminating process: PID={pid}, Command={cmdline}")

                killed = kill_process_tree(pid)
                logger.info(f"Terminated {killed} processes in tree for PID {pid}")

            except Exception as e:
                logger.error(f"Error terminating process: {e}")
    else:
        logger.info("No bot processes found")

    # Remove any Telegram bot lock files
    logger.info("Removing any Telegram bot lock files...")
    for lock_file in lock_files:
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
                logger.info(f"Removed lock file: {lock_file}")
            except OSError as e:
                logger.error(f"Error removing lock file {lock_file}: {e}")

                # If force is true, try even harder to remove locks
                if force:
                    try:
                        logger.warning(f"Forcefully removing lock file: {lock_file}")
                        subprocess.run(['rm', '-f', lock_file], check=False)
                    except Exception as e2:
                        logger.error(f"Force removal failed: {e2}")

    logger.info("✅ Cleanup completed")
    return True

if __name__ == "__main__":
    # Check if force mode is requested
    force_mode = len(sys.argv) > 1 and sys.argv[1] == '--force'

    success = cleanup(force=force_mode)
    sys.exit(0 if success else 1)

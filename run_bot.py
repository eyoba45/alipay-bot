
#!/usr/bin/env python3
"""
Reliable Telegram Bot Runner with automatic recovery
"""
import os
import sys
import time
import subprocess
import logging
import signal
import psutil
import traceback
import threading
import fcntl
import requests
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global variables
bot_process = None
shutdown_requested = False
lock_file = None

def signal_handler(sig, frame):
    """Handle termination signals properly"""
    global shutdown_requested, bot_process
    
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_requested = True
    
    # Terminate bot if running
    if bot_process and bot_process.poll() is None:
        try:
            os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
            logger.info("Sent SIGTERM to bot process group")
            
            # Wait up to 5 seconds for graceful termination
            for _ in range(10):
                if bot_process.poll() is not None:
                    break
                time.sleep(0.5)
                
            # Force kill if still running
            if bot_process.poll() is None:
                os.killpg(os.getpgid(bot_process.pid), signal.SIGKILL)
                logger.info("Sent SIGKILL to bot process group")
        except Exception as e:
            logger.error(f"Error terminating bot: {e}")
    
    # Release lock file
    if lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            if os.path.exists("bot_runner.lock"):
                os.remove("bot_runner.lock")
            logger.info("Released lock file")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")
    
    logger.info("Shutdown complete")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def run_cleanup():
    """Run cleanup to ensure no duplicate processes"""
    try:
        logger.info("Running cleanup...")
        result = subprocess.run(
            [sys.executable, "clean_locks.py"], 
            capture_output=True, 
            text=True,
            check=False  # Don't raise exception on non-zero exit
        )
        
        if result.returncode != 0:
            logger.error(f"Cleanup script returned error code {result.returncode}")
            logger.error(f"Stdout: {result.stdout}")
            logger.error(f"Stderr: {result.stderr}")
            return False
        
        logger.info("Cleanup completed successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to run cleanup: {e}")
        return False

def acquire_lock():
    """Ensure only one instance of the runner is active"""
    global lock_file
    
    try:
        # Create lock file
        lock_file = open("bot_runner.lock", "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("Acquired exclusive lock")
            return True
        except IOError:
            logger.error("Another instance is already running")
            lock_file.close()
            return False
    except Exception as e:
        logger.error(f"Error with lock file: {e}")
        return False

def verify_telegram_token():
    """Verify that the Telegram token is valid and working"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
        return False
    
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10
        )
        
        if response.status_code == 200 and response.json().get('ok'):
            bot_info = response.json().get('result', {})
            logger.info(f"Verified Telegram token for @{bot_info.get('username', 'Unknown')}")
            return True
        else:
            logger.error(f"Invalid Telegram token: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error verifying Telegram token: {e}")
        return False

def start_bot():
    """Start the bot process with proper monitoring"""
    global bot_process
    
    if not run_cleanup():
        logger.error("Failed to clean up environment, proceeding with caution")
    
    # Set up environment variables here if needed
    env = os.environ.copy()
    
    try:
        # Start bot in its own process group
        logger.info("Starting bot process...")
        bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid  # Create new process group
        )
        
        logger.info(f"Bot started with PID {bot_process.pid}")
        
        # Monitor the bot process
        start_time = time.time()
        stdout_lines = []
        
        while not shutdown_requested:
            # Check if process is still running
            if bot_process.poll() is not None:
                exit_code = bot_process.poll()
                
                # Collect any remaining output
                remaining_output, _ = bot_process.communicate()
                if remaining_output:
                    for line in remaining_output.splitlines():
                        stdout_lines.append(line)
                        logger.info(f"Bot output: {line}")
                
                # Log the exit event
                logger.error(f"Bot process exited with code {exit_code}")
                logger.error(f"Last output lines: {stdout_lines[-10:] if stdout_lines else 'No output'}")
                
                # Break the monitoring loop
                return False
            
            # Read output without blocking
            while True:
                line = bot_process.stdout.readline()
                if not line:
                    break
                    
                line = line.strip()
                if line:
                    stdout_lines.append(line)
                    logger.info(f"Bot: {line}")
            
            # Prevent excessive CPU usage
            time.sleep(0.1)
        
        return True
    
    except Exception as e:
        logger.error(f"Error in start_bot: {e}")
        return False

def main():
    """Main function with improved restart logic"""
    global shutdown_requested
    
    logger.info("🚀 Bot runner starting...")
    
    # Verify we have exclusive access
    if not acquire_lock():
        logger.error("Failed to acquire lock, exiting")
        return 1
    
    # Verify Telegram token
    if not verify_telegram_token():
        logger.warning("Failed to verify Telegram token, proceeding anyway")
    
    # Start the bot with restart capability
    max_restarts = 5
    restart_count = 0
    restart_delay = 10  # Initial delay in seconds
    
    while not shutdown_requested and restart_count < max_restarts:
        logger.info(f"Starting bot (attempt {restart_count + 1}/{max_restarts})")
        
        start_time = time.time()
        success = start_bot()
        run_time = time.time() - start_time
        
        if shutdown_requested:
            break
        
        # Handle bot exit
        restart_count += 1
        
        # If the bot ran for more than 5 minutes, reset the restart counter
        if run_time > 300:
            logger.info(f"Bot ran for {run_time:.1f} seconds, resetting restart counter")
            restart_count = 0
            restart_delay = 10
        else:
            # Implement exponential backoff for quick failures
            logger.warning(f"Bot failed after only {run_time:.1f} seconds")
            restart_delay = min(300, restart_delay * 2)
        
        if restart_count < max_restarts:
            logger.info(f"Restarting bot in {restart_delay} seconds...")
            
            # Wait for the delay period, checking for shutdown request
            delay_start = time.time()
            while time.time() - delay_start < restart_delay and not shutdown_requested:
                time.sleep(1)
        else:
            logger.error(f"Maximum restart attempts ({max_restarts}) reached, giving up")
    
    # Cleanup before exit
    if lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            if os.path.exists("bot_runner.lock"):
                os.remove("bot_runner.lock")
        except:
            pass
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        signal_handler(signal.SIGINT, None)
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)

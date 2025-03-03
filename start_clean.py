
#!/usr/bin/env python3
"""
Start script with cleanup - combines clean_locks.py with bot start
"""
import os
import sys
import time
import logging
import subprocess
import signal
import fcntl
import psutil
from threading import Thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Set up signal handling
shutdown_requested = False
bot_process = None
lock_file = None

def signal_handler(sig, frame):
    """Handle termination signals"""
    global shutdown_requested
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_requested = True
    cleanup_and_exit()

def cleanup_and_exit():
    """Clean up resources and exit"""
    global bot_process, lock_file
    
    # Stop bot process if running
    if bot_process:
        try:
            logger.info("Shutting down bot process...")
            if hasattr(bot_process, 'terminate'):
                bot_process.terminate()
                time.sleep(1)
                if bot_process.poll() is None:  # If still running
                    bot_process.kill()
        except Exception as e:
            logger.error(f"Error stopping bot process: {e}")
    
    # Release lock file
    if lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            logger.info("Released lock file")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")
    
    logger.info("Shutdown complete")
    sys.exit(0)

def clean_lock_files():
    """Remove all lock files"""
    logger.info("Checking for lock files...")
    try:
        lock_count = 0
        for file in os.listdir('.'):
            if file.endswith('.lock'):
                try:
                    os.remove(file)
                    lock_count += 1
                except Exception as e:
                    logger.error(f"Error removing lock file {file}: {e}")
        
        logger.info(f"Removed {lock_count} lock files")
        return True
    except Exception as e:
        logger.error(f"Error cleaning lock files: {e}")
        return False

def find_and_terminate_bot_processes():
    """Find and terminate any existing bot processes"""
    logger.info("Terminating any existing bot processes...")
    
    # List of bot-related scripts
    bot_scripts = ['bot.py', 'run_bot.py', 'forever.py', 'monitor_bot.py', 
                  'keep_alive.py', 'simple_bot.py', 'robust_bot.py']
    
    terminated_count = 0
    my_pid = os.getpid()
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            # Skip our own process
            if proc.pid == my_pid:
                continue
                
            # Check if this is a Python process
            if proc.info['name'] in ['python', 'python3']:
                cmdline = proc.info['cmdline'] if proc.info['cmdline'] else []
                cmdline_str = ' '.join(cmdline) if cmdline else ''
                
                # Check if it's running any of our bot scripts
                if any(script in cmdline_str for script in bot_scripts):
                    logger.info(f"Terminating bot process: {proc.pid} ({cmdline_str})")
                    proc.terminate()
                    terminated_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    if terminated_count == 0:
        logger.info("No bot processes found")
    else:
        logger.info(f"Terminated {terminated_count} bot processes")
        # Give processes time to terminate
        time.sleep(1)
    
    return True

def acquire_lock():
    """Acquire an exclusive lock"""
    global lock_file
    
    try:
        lock_file = open("bot_runner.lock", "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info("Acquired exclusive lock")
            return True
        except IOError:
            logger.error("Another instance is already running")
            lock_file.close()
            lock_file = None
            return False
    except Exception as e:
        logger.error(f"Error with lock file: {e}")
        return False

def verify_telegram_token():
    """Verify that the Telegram bot token is valid"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
        return False
    
    logger.info("Verifying Telegram token...")
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if response.status_code == 200 and response.json().get('ok'):
            bot_info = response.json().get('result', {})
            logger.info(f"Verified Telegram token for @{bot_info.get('username')}")
            return True
        else:
            logger.error(f"Invalid Telegram token: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error verifying Telegram token: {e}")
        return False

def start_keep_alive():
    """Start the keep-alive server"""
    try:
        from keep_alive import keep_alive
        logger.info("Starting keep-alive server...")
        keep_alive()
        return True
    except Exception as e:
        logger.error(f"Error starting keep-alive server: {e}")
        return False

def run_bot(max_attempts=5):
    """Run the bot with multiple retry attempts"""
    global bot_process
    
    for attempt in range(1, max_attempts + 1):
        if shutdown_requested:
            return False
            
        logger.info(f"Starting bot (attempt {attempt}/{max_attempts})")
        try:
            # Run cleanup first
            logger.info("Running cleanup...")
            subprocess.run([sys.executable, "clean_locks.py"], check=True)
            
            # Start the bot
            logger.info("Starting bot process...")
            bot_process = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # Wait for process to finish or be terminated
            return_code = bot_process.wait()
            
            if shutdown_requested:
                logger.info("Shutdown requested, not restarting bot")
                return False
                
            if return_code == 0:
                logger.info("Bot process exited normally")
                return True
            else:
                logger.error(f"Bot process exited with code {return_code}")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Error in subprocess: {e}")
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            
        # Wait before retry
        if attempt < max_attempts:
            wait_time = min(60, 5 * 2**attempt)
            logger.info(f"Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
    
    logger.error(f"Failed to start bot after {max_attempts} attempts")
    return False

def main():
    """Main function"""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("🧹 Starting cleanup...")
    
    # Clean up existing processes and lock files
    find_and_terminate_bot_processes()
    clean_lock_files()
    
    # Acquire lock to ensure only one instance runs
    if not acquire_lock():
        logger.error("Failed to acquire lock, exiting")
        return 1
        
    # Verify environment
    if not verify_telegram_token():
        logger.error("Failed to verify Telegram token, exiting")
        cleanup_and_exit()
        return 1
    
    # Start the keep-alive server
    start_keep_alive()
    
    # Start the bot
    success = run_bot()
    
    # Clean up and exit
    cleanup_and_exit()
    return 0 if success else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)

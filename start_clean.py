#!/usr/bin/env python3
"""
Clean startup script for the bot that ensures a clean environment.
"""
import os
import sys
import time
import logging
import subprocess
import signal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def run_command(command, check=False):
    """Run a shell command"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=check)
        if result.returncode != 0:
            logger.warning(f"Command failed with code {result.returncode}: {command}")
            if result.stderr:
                logger.warning(f"Error output: {result.stderr}")
        return result
    except Exception as e:
        logger.error(f"Error running command '{command}': {e}")
        return None

def cleanup_environment():
    """Clean up any existing bot processes and lock files"""
    logger.info("Cleaning up environment...")
    
    # Kill any running bot processes
    run_command("pkill -f 'python.*bot.py' || true")
    run_command("pkill -f 'telebot' || true")
    run_command("pkill -f 'keep_alive.py' || true")
    run_command("pkill -f 'monitor_bot.py' || true")
    
    # Remove lock files
    run_command("rm -f *.lock || true")
    run_command("rm -f *.pid || true")
    
    # Give processes time to terminate
    time.sleep(2)
    
    return True

def start_keep_alive():
    """Start the keep-alive server"""
    logger.info("Starting keep-alive server...")
    
    # Check if keep_alive.py exists
    if not os.path.exists("keep_alive.py"):
        logger.error("keep_alive.py not found!")
        return False
        
    # Start keep-alive in background
    process = subprocess.Popen(
        [sys.executable, "keep_alive.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True
    )
    
    logger.info(f"Keep-alive server started with PID: {process.pid}")
    
    # Wait for server to start
    time.sleep(5)
    
    # Check if server is responding
    try:
        result = run_command("curl -s http://localhost:5000/ping")
        if result and "pong" in result.stdout:
            logger.info("Keep-alive server is responding")
            return True
        else:
            logger.warning("Keep-alive server not responding properly")
            return False
    except Exception as e:
        logger.error(f"Error checking keep-alive server: {e}")
        return False

def start_bot_monitor():
    """Start the bot monitor"""
    logger.info("Starting bot monitor...")
    
    # Check if monitor_bot.py exists
    if not os.path.exists("monitor_bot.py"):
        logger.error("monitor_bot.py not found!")
        return False
        
    # Create a monitor startup script for better reliability
    with open("start_monitor.py", "w") as f:
        f.write("""#!/usr/bin/env python3
import os
import sys
import time
import logging
import subprocess

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor_starter.log")
    ]
)
logger = logging.getLogger(__name__)

logger.info("Starting bot monitor wrapper...")

try:
    # Verify monitor_bot.py exists
    if not os.path.exists("monitor_bot.py"):
        logger.error("monitor_bot.py not found!")
        sys.exit(1)
        
    # Set environment variables
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUNBUFFERED'] = '1'
    
    # Start monitor process
    process = subprocess.Popen(
        [sys.executable, "monitor_bot.py"],
        env=env,
        start_new_session=True
    )
    
    logger.info(f"Bot monitor started with PID: {process.pid}")
    
    # Keep this process running to ensure the monitor stays active
    while True:
        time.sleep(60)
        # Check if process is still running
        if process.poll() is not None:
            logger.error("Bot monitor terminated, restarting...")
            process = subprocess.Popen(
                [sys.executable, "monitor_bot.py"],
                env=env,
                start_new_session=True
            )
            logger.info(f"Bot monitor restarted with PID: {process.pid}")
            
except Exception as e:
    logger.error(f"Error in monitor wrapper: {e}")
    import traceback
    logger.error(traceback.format_exc())
    sys.exit(1)
""")
        
    # Set executable permission
    try:
        os.chmod("start_monitor.py", 0o755)
    except Exception as e:
        logger.warning(f"Could not set executable permission: {e}")
    
    # Redirect output to log files
    stdout_log = open("monitor_stdout.log", "a")
    stderr_log = open("monitor_stderr.log", "a")
    
    # Start monitor process with the wrapper
    process = subprocess.Popen(
        [sys.executable, "start_monitor.py"],
        stdout=stdout_log,
        stderr=stderr_log,
        start_new_session=True
    )
    
    logger.info(f"Bot monitor started with PID: {process.pid}")
    time.sleep(2)
    
    # Check if process is still running
    if process.poll() is not None:
        logger.error("Bot monitor process terminated unexpectedly")
        # Check for error output
        with open("monitor_stderr.log", "r") as f:
            errors = f.read().strip()
            if errors:
                logger.error(f"Monitor errors: {errors}")
        return False
        
    logger.info("Bot monitor running successfully")
    return True

def start_payment_notifier():
    """Start the payment notification service"""
    logger.info("Starting payment notification service...")
    
    # Check if chapa_autopay.py exists - this is our enhanced auto-approval script
    if os.path.exists("chapa_autopay.py"):
        logger.info("Using enhanced auto-approval payment verification service")
        script_name = "chapa_autopay.py"
    elif os.path.exists("payment_notifier.py"):
        logger.info("Using standard payment notification service")
        script_name = "payment_notifier.py"
    else:
        logger.error("Payment notification service scripts not found!")
        return False
    
    try:    
        # Start payment notifier in background with proper output redirection
        log_file = open("payment_notifier_stdout.log", "a")
        err_file = open("payment_notifier_stderr.log", "a")
        
        process = subprocess.Popen(
            [sys.executable, script_name],
            stdout=log_file,
            stderr=err_file,
            start_new_session=True
        )
        
        logger.info(f"Payment notification service started with PID: {process.pid}")
        time.sleep(2)
        
        # Check if process is still running
        if process.poll() is not None:
            logger.error("Payment notification process terminated unexpectedly")
            # Check for error output
            with open("payment_notifier_stderr.log", "r") as f:
                errors = f.read().strip()
                if errors:
                    logger.error(f"Payment notifier errors: {errors}")
            return False
            
        logger.info("Payment notification service running successfully")
        if script_name == "chapa_autopay.py":
            logger.info("✅ Auto-approval for payments is now enabled via Chapa verification")
        return True
    except Exception as e:
        logger.error(f"Failed to start payment notification service: {e}")
        return False

def main():
    """Main function"""
    try:
        logger.info("Starting bot runner...")
        
        # Clean up environment
        cleanup_environment()
        
        # Start keep-alive server
        try:
            keep_alive_ok = start_keep_alive()
            if not keep_alive_ok:
                logger.warning("Keep-alive module not found, continuing without it")
        except Exception as e:
            logger.warning(f"Error starting keep-alive: {e}")
        
        # Start payment notification service
        try:
            payment_notifier_ok = start_payment_notifier()
            if not payment_notifier_ok:
                logger.warning("Payment notification service failed to start, continuing without it")
        except Exception as e:
            logger.warning(f"Error starting payment notification service: {e}")
        
        # Start bot monitor
        monitor_ok = start_bot_monitor()
        if not monitor_ok:
            logger.error("Failed to start bot monitor")
            return 1
            
        logger.info("Bot startup complete")
        return 0
        
    except KeyboardInterrupt:
        logger.info("Startup interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Error in main: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

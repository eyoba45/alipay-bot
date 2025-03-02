#!/usr/bin/env python3
"""Script to run the Telegram bot with uptime server"""

import os
import sys
import time
import subprocess
import signal
import logging
# Added import for keep_alive function
from keep_alive import keep_alive

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Global variables
bot_process = None

def cleanup_environment():
    """Clean up any existing bot processes or lock files"""
    global bot_process
    try:
        print("🧹 Cleaning up environment...")

        # First try to stop our own process if running
        if bot_process:
            try:
                bot_process.terminate()
                time.sleep(1)
                if bot_process.poll() is None:
                    bot_process.kill()
                print("✅ Stopped existing bot process")
            except Exception as e:
                print(f"❌ Error stopping bot process: {e}")

        # Run the cleanup script
        print("🧹 Starting cleanup process...")
        try:
            subprocess.run(
                [sys.executable, "clean_locks.py"],
                check=True,
                timeout=30
            )
            print("✅ Cleanup completed")
        except subprocess.SubprocessError as e:
            print(f"⚠️ Cleanup script error: {e}")

        # Extra safety: force kill any remaining processes
        print("🔍 Checking for running bot processes...")
        try:
            # More comprehensive cleanup
            kill_commands = [
                "pkill -f 'python.*bot.py' || true",
                "pkill -f 'monitor_bot.py' || true", 
                "pkill -f 'telebot' || true"
            ]
            
            for cmd in kill_commands:
                subprocess.run(cmd, shell=True, check=False)
                
            time.sleep(2)  # Allow processes to terminate
        except Exception as e:
            print(f"⚠️ Process cleanup error: {e}")

        # Verify no bot processes are running
        time.sleep(1)

    except Exception as e:
        print(f"❌ Error during environment cleanup: {e}")

def start_bot():
    """Start the bot with monitoring"""
    try:
        logger.info("🚀 Starting bot...")

        # Start the uptime server
        keep_alive()
        logger.info("✅ Uptime server started on port 8080")

        # Start the bot process  - using original cleanup method
        cleanup_environment()
        
        # Verify Telegram setup first
        print("🔍 Checking Telegram bot configuration...")
        try:
            check_result = subprocess.run(
                [sys.executable, "check_telegram_setup.py"],
                check=False,
                timeout=30,
                capture_output=True,
                text=True
            )
            print(check_result.stdout)
            
            if "configured correctly" not in check_result.stdout:
                print("❌ Telegram bot is not configured correctly. Please check your token.")
                return False
        except Exception as e:
            print(f"⚠️ Error checking Telegram setup: {e}")

        # Start the monitor process with environment variables
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'  # Ensure output is not buffered
        
        global bot_process
        bot_process = subprocess.Popen(
            [sys.executable, "monitor_bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            env=env,
            preexec_fn=os.setsid  # Create a new process group
        )

        print(f"✅ Bot monitor started with PID: {bot_process.pid}")

        # Monitor the output
        while True:
            output = bot_process.stdout.readline()
            if not output and bot_process.poll() is not None:
                if bot_process.returncode != 0:
                    print(f"⚠️ Bot monitor process exited with error code: {bot_process.returncode}")
                    return False
                print("✅ Bot monitor process completed successfully")
                return True
                
            if output:
                print(output.strip())

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("👋 Shutting down bot...")
        cleanup_environment()
        return False
    except Exception as e:
        print(f"❌ Error running bot: {e}")
        cleanup_environment()
        return False

if __name__ == "__main__":
    start_bot()


# Dummy keep_alive.py and bot.py files for Replit execution

# keep_alive.py
def keep_alive():
    print("Keep-alive function running...")
    # Add your keep-alive logic here (e.g., using Flask or similar)


# bot.py
def run_bot():
    print("Bot running...")
    # Add your Telegram bot logic here
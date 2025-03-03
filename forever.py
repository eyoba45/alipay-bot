#!/usr/bin/env python3
"""
Forever script to keep the bot running continuously with proper signal handling
"""
import os
import sys
import time
import signal
import logging
import subprocess
import traceback
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot_uptime.log")
    ]
)
logger = logging.getLogger(__name__)

# Global variables
bot_process = None
shutdown_requested = False

def signal_handler(sig, frame):
    """Handle termination signals gracefully"""
    global shutdown_requested, bot_process

    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_requested = True

    if bot_process:
        try:
            logger.info("Sending termination signal to bot process...")
            # Send SIGTERM to allow for graceful shutdown
            if hasattr(bot_process, 'pid'):
                os.kill(bot_process.pid, signal.SIGTERM)

            # Give the process some time to terminate gracefully
            for _ in range(5):  # Wait up to 5 seconds
                if bot_process.poll() is not None:
                    logger.info("Bot process terminated gracefully")
                    break
                time.sleep(1)

            # Force kill if still running
            if bot_process.poll() is None:
                logger.warning("Bot process did not terminate gracefully, forcing...")
                if hasattr(bot_process, 'pid'):
                    os.kill(bot_process.pid, signal.SIGKILL)
        except Exception as e:
            logger.error(f"Error terminating bot process: {e}")

    logger.info("Shutdown complete")
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def run_bot_with_restart():
    """Run the bot with automatic restart on failure"""
    global bot_process

    restart_count = 0
    max_restarts = 15  # Increased restart attempts

    while not shutdown_requested and restart_count < max_restarts:
        try:
            # Run the clean_locks.py script first
            logger.info("Cleaning up any lock files...")
            subprocess.run([sys.executable, "clean_locks.py"], 
                          check=True, 
                          stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)

            logger.info("Starting bot process...")

            # Start the bot process
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'  # Ensure output is not buffered

            # Try to check for syntax errors before starting the bot
            try:
                logger.info("Checking for syntax errors before starting bot...")
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", "bot.py"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode != 0:
                    logger.error(f"⚠️ Syntax check failed: {result.stderr}")
                    logger.error("❌ Unable to start bot due to syntax errors. Please fix and try again.")
                    time.sleep(10)
                    continue
                logger.info("✅ No syntax errors detected")
            except Exception as e:
                logger.warning(f"⚠️ Syntax check failed: {e}")
                
            # Start the actual bot process
            bot_process = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                env=env
            )

            logger.info(f"Bot process started with PID: {bot_process.pid}")

            # Monitor the output
            while not shutdown_requested:
                output = bot_process.stdout.readline()
                if not output and bot_process.poll() is not None:
                    break
                if output:
                    print(output.strip())

            # Check if the process exited
            if bot_process.poll() is not None:
                exit_code = bot_process.returncode
                logger.warning(f"Bot process exited with code: {exit_code}")

                if shutdown_requested:
                    logger.info("Shutdown was requested, not restarting")
                    break

                restart_count += 1

                # Exponential backoff for restarts
                wait_time = min(60, 5 * (2 ** min(restart_count, 5)))
                logger.info(f"Restarting in {wait_time} seconds (attempt {restart_count}/{max_restarts})...")
                time.sleep(wait_time)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in bot runner: {traceback.format_exc()}")
            restart_count += 1
            time.sleep(5)

    if restart_count >= max_restarts:
        logger.error(f"Exceeded maximum restart attempts ({max_restarts}), giving up")

def clear_webhook():
    """Clear any existing webhook"""
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set")
        return False

    try:
        logger.info("🔄 Clearing Telegram webhook...")
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            logger.info("✅ Webhook cleared successfully")
            return True
        else:
            logger.error(f"❌ Failed to clear webhook: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Error clearing webhook: {e}")
        return False

def cleanup_environment():
    """Clean up any existing bot processes"""
    try:
        logger.info("🧹 Cleaning environment...")

        # Kill any existing bot processes
        cleanup_commands = [
            "pkill -9 -f 'python.*bot.py' || true",
            "pkill -9 -f 'telebot' || true",
            "rm -f *.lock || true"
        ]

        for cmd in cleanup_commands:
            try:
                subprocess.run(cmd, shell=True, check=False)
            except Exception as e:
                logger.error(f"Cleanup command error: {e}")

        # Clear webhook
        clear_webhook()

        time.sleep(2)  # Give processes time to fully terminate
        logger.info("✅ Environment cleaned")
        return True
    except Exception as e:
        logger.error(f"❌ Error during cleanup: {e}")
        return False

def verify_telegram_connection():
    """Verify that we can connect to Telegram API"""
    try:
        TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN not set")
            return False

        # Check for ADMIN_CHAT_ID and set default if missing
        if not os.environ.get('ADMIN_CHAT_ID'):
            logger.warning("⚠️ ADMIN_CHAT_ID not found, setting default value")
            os.environ['ADMIN_CHAT_ID'] = '1234567890'  # Set a default value

        # Check for DATABASE_URL and set default if missing
        if not os.environ.get('DATABASE_URL'):
            logger.warning("⚠️ DATABASE_URL not found, setting default value")
            os.environ['DATABASE_URL'] = 'sqlite:///bot.db'  # Use SQLite by default

        logger.info("🔑 Testing Telegram API connection...")
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)

        if response.status_code == 200:
            bot_info = response.json().get('result', {})
            logger.info(f"✅ Telegram API connection verified: @{bot_info.get('username', 'unknown')}")
            return True
        else:
            logger.error(f"❌ Telegram API connection failed: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ Telegram API test failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting bot runner...")
    try:
        # Import keep_alive if available
        try:
            from keep_alive import keep_alive
            keep_alive()
            logger.info("Keep-alive server started")
        except ImportError:
            logger.warning("Keep-alive module not found, continuing without it")

        run_bot_with_restart()
    except Exception as e:
        logger.critical(f"Critical error in main: {traceback.format_exc()}")
    finally:
        logger.info("Bot runner exiting")

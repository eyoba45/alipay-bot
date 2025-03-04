#!/usr/bin/env python3
"""
Forever runner script with improved error handling
"""
import os
import sys
import time
import logging
import subprocess
import signal
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_uptime.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global flag for shutdown
shutdown_requested = False

def signal_handler(sig, frame):
    """Handle termination signals"""
    global shutdown_requested
    logger.info(f"Received signal {sig}, initiating shutdown...")
    shutdown_requested = True

def run_clean_locks():
    """Run the clean_locks script to ensure clean environment"""
    logger.info("🧹 Running cleanup...")
    try:
        subprocess.run([sys.executable, "clean_locks.py"], check=True)
        logger.info("✅ Cleanup completed")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Cleanup failed with code {e.returncode}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error in cleanup: {e}")
        logger.error(traceback.format_exc())
        return False

def start_bot():
    """Start the bot process and monitor it"""
    logger.info("🚀 Starting bot process...")

    try:
        process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        logger.info(f"✅ Bot started with PID {process.pid}")

        # Read and log output
        while process.poll() is None and not shutdown_requested:
            line = process.stdout.readline()
            if line:
                print(line.strip())  # Echo to console
                if "ERROR" in line or "Exception" in line:
                    logger.error(f"⚠️ Bot error: {line.strip()}")

        # Check exit status
        exit_code = process.returncode
        if exit_code is not None:
            logger.info(f"Bot exited with code {exit_code}")
            if exit_code != 0:
                logger.error(f"❌ Bot exited with error code {exit_code}")

        return exit_code
    except Exception as e:
        logger.error(f"❌ Error starting bot: {e}")
        logger.error(traceback.format_exc())
        return 1

def main():
    """Main runner with restart logic"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    failures = 0

    while not shutdown_requested:
        # Run cleanup before starting
        if not run_clean_locks():
            logger.error("❌ Critical: Cleanup failed. Waiting 30s before retry...")
            time.sleep(30)
            continue

        # Start the bot
        exit_code = start_bot()

        # Handle restart logic
        if shutdown_requested:
            logger.info("👋 Shutdown requested, exiting")
            break

        if exit_code != 0:
            failures += 1

            # Exponential backoff for repeated failures
            wait_time = min(300, 5 * (2 ** min(failures, 6)))
            logger.warning(f"⚠️ Bot failed, attempt {failures}. Waiting {wait_time}s before restart...")

            # Deep clean if many failures
            if failures > 3:
                logger.warning("🧨 Multiple failures detected. Performing deep cleanup...")
                try:
                    # Kill all python processes (except this one)
                    os.system(f"pkill -9 -f 'python' -P 1")
                    os.system("rm -f *.lock")
                except Exception as e:
                    logger.error(f"❌ Deep cleanup error: {e}")

            # Wait before retry
            time.sleep(wait_time)
        else:
            # Reset failure counter on clean exit
            failures = 0
            logger.info("Bot exited normally. Restarting in 5s...")
            time.sleep(5)

if __name__ == "__main__":
    logger.info("🔄 Forever runner starting")
    try:
        main()
    except KeyboardInterrupt:
        logger.info("👋 User requested shutdown")
    except Exception as e:
        logger.error(f"❌ Fatal error in runner: {e}")
        logger.error(traceback.format_exc())
    finally:
        logger.info("👋 Forever runner exiting")

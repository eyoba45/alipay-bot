#!/usr/bin/env python3
"""
Consolidated bot starter with cleanup and keep-alive server
"""
import os
import sys
import time
import logging
import subprocess
import signal
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Global flags
shutdown_requested = False
bot_process = None

def signal_handler(sig, frame):
    """Handle termination signals"""
    global shutdown_requested
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_requested = True
    cleanup_and_exit()

def cleanup_and_exit():
    """Clean up resources and exit"""
    global bot_process

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

    logger.info("Shutdown complete")
    sys.exit(0)

def start_keep_alive():
    """Start the keep-alive server in a separate thread"""
    try:
        from keep_alive import keep_alive
        logger.info("Starting keep-alive server...")
        keep_alive()
        logger.info("Keep-alive server started")
        return True
    except Exception as e:
        logger.error(f"Error starting keep-alive server: {e}")
        return False

def run_cleanup():
    """Run the cleanup script"""
    try:
        logger.info("Cleaning up any lock files...")
        result = subprocess.run(
            [sys.executable, "clean_locks.py"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        logger.info("Cleanup completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Cleanup failed with exit code {e.returncode}")
        logger.error(f"Output: {e.output}")
        return False
    except Exception as e:
        logger.error(f"Error running cleanup: {e}")
        return False

def run_bot():
    """Run the bot with proper error handling"""
    global bot_process

    try:
        logger.info("Starting bot process...")
        # Start the bot
        bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Monitor the bot process output
        for line in bot_process.stdout:
            print(line, end='')

        # Wait for process to finish or be terminated
        return_code = bot_process.wait()
        logger.info(f"Bot process exited with code {return_code}")

        return return_code == 0

    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        return False

def verify_environment():
    """Verify that required environment variables are set"""
    required_vars = ['TELEGRAM_BOT_TOKEN', 'DATABASE_URL']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False

    logger.info("Environment variables verified")
    return True

def main():
    """Main function"""
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting bot runner...")

    # Verify environment
    if not verify_environment():
        logger.error("Failed to verify environment, exiting")
        return 1

    # Run cleanup
    if not run_cleanup():
        logger.warning("Cleanup had issues, but continuing...")

    # Start the keep-alive server
    start_keep_alive()

    # Run the bot
    max_restarts = 5
    restart_count = 0
    restart_delay = 10  # seconds

    while not shutdown_requested and restart_count < max_restarts:
        logger.info(f"Starting bot (attempt {restart_count + 1}/{max_restarts})")

        start_time = time.time()
        success = run_bot()
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
            time.sleep(restart_delay)

    logger.info("Bot runner exiting")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)

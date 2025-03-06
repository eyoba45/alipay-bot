#!/usr/bin/env python3
"""
Clean startup script for Telegram bot runner with Chapa webhook server
"""
import sys
import os
import logging
import time
import subprocess
import signal
import threading
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='bot_starter.log',
    filemode='a'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

logger = logging.getLogger(__name__)

def run_bot():
    """Run the main bot process"""
    try:
        logger.info("Starting main bot process...")
        env = os.environ.copy()

        # Run the bot with subprocess for better control
        bot_process = subprocess.Popen(
            ["python", "bot.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        # Process and log the bot output in a separate thread
        def log_output():
            for line in bot_process.stdout:
                logger.info(f"Bot output: {line.strip()}")

        log_thread = threading.Thread(target=log_output, daemon=True)
        log_thread.start()

        return bot_process
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        return None

def run_webhook_server():
    """Run the Chapa webhook server if Chapa integration is enabled"""
    # Check if Chapa secret key is set
    if not os.environ.get('CHAPA_SECRET_KEY'):
        logger.info("Chapa integration not configured, skipping webhook server")
        return None

    try:
        logger.info("Starting Chapa webhook server...")
        env = os.environ.copy()

        # Run the webhook server.  Assumes chapa_webhook.py handles automatic approval.
        webhook_process = subprocess.Popen(
            ["python", "chapa_webhook.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        # Process and log the webhook server output in a separate thread
        def log_output():
            for line in webhook_process.stdout:
                logger.info(f"Webhook server output: {line.strip()}")

        log_thread = threading.Thread(target=log_output, daemon=True)
        log_thread.start()

        # Give the webhook server time to start up
        time.sleep(2)
        logger.info("Chapa webhook server started")

        return webhook_process
    except Exception as e:
        logger.error(f"Error running webhook server: {e}")
        return None

def run_payment_verifier():
    """Run the Chapa payment verifier if Chapa integration is enabled"""
    # Check if Chapa secret key is set
    if not os.environ.get('CHAPA_SECRET_KEY'):
        logger.info("Chapa integration not configured, skipping payment verifier")
        return None

    try:
        logger.info("Starting Chapa payment verifier...")
        env = os.environ.copy()

        # Run the payment verifier
        verifier_process = subprocess.Popen(
            ["python", "chapa_payment_verifier.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )

        # Process and log the verifier output in a separate thread
        def log_output():
            for line in verifier_process.stdout:
                logger.info(f"Payment verifier output: {line.strip()}")

        log_thread = threading.Thread(target=log_output, daemon=True)
        log_thread.start()

        return verifier_process
    except Exception as e:
        logger.error(f"Error running payment verifier: {e}")
        return None

def main():
    """Main function to start the bot with clean environment"""
    logger.info("Starting bot with clean environment...")

    # First, run the cleanup script
    try:
        logger.info("Running cleanup script...")
        subprocess.run(["python", "clean_locks.py"], check=True)
        logger.info("Cleanup complete")
    except subprocess.CalledProcessError as e:
        logger.error(f"Cleanup failed with error code {e.returncode}")
        return 1
    except Exception as e:
        logger.error(f"Error running cleanup: {e}")
        return 1

    # Start the bot and additional services
    processes = []

    # Run the main bot
    bot_process = run_bot()
    if bot_process:
        processes.append(('bot', bot_process))
    else:
        logger.error("Failed to start bot process")
        return 1

    # Always start webhook server to capture payments
    webhook_process = run_webhook_server()
    if webhook_process:
        processes.append(('webhook', webhook_process))
    else:
        logger.error("Failed to start webhook server")
        # Decide whether to continue or exit based on requirements.
        # return 1  # Uncomment to exit if webhook fails


    # Run the payment verifier if Chapa is configured
    verifier_process = run_payment_verifier()
    if verifier_process:
        processes.append(('verifier', verifier_process))

    # Set up signal handler for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down gracefully...")
        for name, process in processes:
            logger.info(f"Terminating {name} process...")
            try:
                process.terminate()
                process.wait(timeout=5)
                logger.info(f"{name} process terminated")
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} process did not terminate, killing...")
                process.kill()
            except Exception as e:
                logger.error(f"Error terminating {name} process: {e}")
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Wait for bot process to exit
    try:
        while True:
            # Check if bot process is still running
            if bot_process.poll() is not None:
                return_code = bot_process.returncode
                logger.info(f"Bot process exited with code {return_code}")
                break

            # Sleep to avoid CPU spinning
            time.sleep(1)

        # If we reach here, bot process has exited, terminate other processes
        for name, process in processes:
            if process.poll() is None:
                logger.info(f"Terminating {name} process...")
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                except Exception as e:
                    logger.error(f"Error terminating {name} process: {e}")

        if return_code != 0:
            logger.error("Bot process exited with error")
            return 1

        return 0
    except KeyboardInterrupt:
        # Handle Ctrl+C
        logger.info("Received keyboard interrupt, shutting down...")
        signal_handler(signal.SIGINT, None)
        return 0

if __name__ == "__main__":
    sys.exit(main())

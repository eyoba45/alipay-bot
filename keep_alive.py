import os
import sys
import time
import logging
import threading
import signal
import subprocess
from flask import Flask
from threading import Thread

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

# Flask app for keep-alive ping
app = Flask(__name__)
bot_process = None
last_heartbeat = time.time()

@app.route('/')
def home():
    return "Telegram Bot is alive! 🤖"

@app.route('/ping')
def ping():
    return "pong"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    server = Thread(target=run)
    server.daemon = True
    server.start()
    logger.info("Keep-alive server started on port 8080")

def cleanup_environment():
    """Clean up any existing bot processes or lock files"""
    try:
        logger.info("🧹 Cleaning up environment...")

        # Clean up lock files
        lock_files = [
            "bot_instance.lock",
            "telegram_bot.lock",
            "*.pyc"  # Clean compiled python files
        ]
        for lock_file in lock_files:
            try:
                if "*" in lock_file:
                    subprocess.run(f"rm -f {lock_file}", shell=True, check=False)
                elif os.path.exists(lock_file):
                    os.remove(lock_file)
                    logger.info(f"✅ Removed lock file: {lock_file}")
            except Exception as e:
                logger.warning(f"⚠️ Lock file removal warning: {e}")

        # Extra safety for processes
        try:
            kill_commands = [
                "pkill -f 'python.*bot.py' || true",
                "pkill -f 'monitor_bot.py' || true", 
                "pkill -f 'telebot' || true"
            ]

            for cmd in kill_commands:
                subprocess.run(cmd, shell=True, check=False)
        except Exception as e:
            logger.error(f"⚠️ Process cleanup error: {e}")

        logger.info("✅ Environment cleanup completed")

    except Exception as e:
        logger.error(f"❌ Error during environment cleanup: {e}")

def main():
    """Main function"""
    global bot_process, last_heartbeat

    try:
        # Initial setup
        cleanup_environment()
        keep_alive() # Start Flask server

        restart_count = 0
        restart_reset_time = time.time()

        while True:
            try:
                # Reset restart count every hour
                if time.time() - restart_reset_time > 3600:
                    restart_count = 0
                    restart_reset_time = time.time()
                    logger.info("🔄 Reset restart counter")

                # Check if we need to start the bot
                if bot_process is None or bot_process.poll() is not None:
                    if bot_process is not None:
                        logger.warning(f"⚠️ Bot process exited with code: {bot_process.poll()}")

                    logger.info(f"🚀 Starting bot (attempt {restart_count + 1})...")
                    # Start the bot
                    env = os.environ.copy()
                    env['PYTHONUNBUFFERED'] = '1'

                    bot_process = subprocess.Popen(
                        [sys.executable, "bot.py"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        universal_newlines=True,
                        bufsize=1,
                        env=env
                    )

                    last_heartbeat = time.time()
                    restart_count += 1
                    logger.info(f"✅ Bot started with PID: {bot_process.pid}")

                    # If too many restarts, wait longer
                    if restart_count > 10:
                        wait_time = min(300, 30 * (restart_count - 10))
                        logger.warning(f"⚠️ Too many restarts ({restart_count}), waiting {wait_time}s...")
                        time.sleep(wait_time)

                # Read process output
                if bot_process and bot_process.stdout:
                    while True:
                        output = bot_process.stdout.readline(1024)
                        if not output:
                            break

                        output = output.strip()
                        if output:
                            logger.info(f"🤖 Bot: {output}")
                            if "Bot is running" in output or "Successfully" in output:
                                last_heartbeat = time.time()

                # Check if heartbeat is too old
                if time.time() - last_heartbeat > 300:  # 5 minutes
                    logger.warning("⚠️ Bot heartbeat timeout, restarting...")
                    if bot_process:
                        try:
                            bot_process.terminate()
                            time.sleep(2)
                            if bot_process.poll() is None:
                                bot_process.kill()
                        except:
                            pass
                    bot_process = None

                # Log heartbeat
                logger.info("💓 Monitor heartbeat")
                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("👋 Shutting down...")
                if bot_process:
                    bot_process.terminate()
                return
            except Exception as e:
                logger.error(f"❌ Monitor error: {e}")
                time.sleep(5)
    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")
        if bot_process:
            bot_process.terminate()
    except Exception as e:
        logger.error(f"❌ Fatal error in main: {e}")

if __name__ == "__main__":
    main()
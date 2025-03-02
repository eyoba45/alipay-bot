#!/usr/bin/env python3
"""
Forever - A robust process manager to keep Telegram bot running 24/7 on Replit
"""
import os
import sys
import time
import signal
import logging
import subprocess
import threading
import traceback
import requests
from datetime import datetime
from flask import Flask
from threading import Thread

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("FOREVER")

# Global variables
bot_process = None
shutdown_requested = False
last_restart_time = time.time()
restart_count = 0

# Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    """Home endpoint for keep-alive pings"""
    # Get info about running bot
    bot_status = "RUNNING" if bot_process and bot_process.poll() is None else "STOPPED"
    uptime = time.time() - last_restart_time if bot_process else 0

    # Create status message
    status = {
        "status": bot_status,
        "uptime": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m {int(uptime % 60)}s",
        "restarts": restart_count,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    logger.info(f"✅ Received keep-alive ping, bot is {bot_status}")
    return f"Bot is {bot_status}! Uptime: {status['uptime']}, Restarts: {restart_count}"

@app.route('/ping')
def ping():
    """Simple ping endpoint for monitoring services"""
    return "pong"

def run_flask():
    """Run Flask server in a separate thread"""
    app.run(host='0.0.0.0', port=8080, threaded=True)

def signal_handler(signum, frame):
    """Handle termination signals"""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_requested = True
    if bot_process:
        try:
            os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
        except:
            pass

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

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

def start_bot():
    """Start the bot directly"""
    global bot_process, last_restart_time, restart_count

    try:
        logger.info("🚀 Starting bot process...")

        # First, verify Telegram connection
        if not verify_telegram_connection():
            logger.warning("⚠️ Telegram connection failed, but continuing anyway...")

        # Environment variables for better stability
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        env['REPLIT_KEEP_ALIVE'] = '1'
        env['BOT_STARTED_AT'] = str(int(time.time()))

        # Start bot.py process
        bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            env=env,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None  # Create process group on Unix
        )

        last_restart_time = time.time()
        restart_count += 1

        # Wait a moment and check for immediate crash
        time.sleep(5)
        if bot_process.poll() is not None:
            # Process already exited
            exit_code = bot_process.poll()
            output, _ = bot_process.communicate()
            logger.error(f"❌ Bot crashed immediately with exit code {exit_code}")
            logger.error(f"Bot output: {output}")
            return False

        logger.info(f"✅ Bot started with PID: {bot_process.pid}")

        # Start a thread to read output
        output_thread = threading.Thread(target=read_output)
        output_thread.daemon = True
        output_thread.start()

        return True

    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return False

def read_output():
    """Read and log output from the bot process"""
    global bot_process

    if not bot_process:
        return

    try:
        while True:
            line = bot_process.stdout.readline()
            if not line:
                break

            line = line.strip()
            if line:
                print(f"BOT: {line}")
    except Exception as e:
        logger.error(f"Error reading output: {e}")


def check_bot_health():
    """Check if bot is still running and healthy"""
    global bot_process

    if bot_process is None:
        logger.error("❌ No bot process found")
        return False

    # Check if process still exists
    if bot_process.poll() is not None:
        logger.error(f"❌ Bot process has exited with code {bot_process.poll()}")
        return False

    # Try to ping Telegram API to verify connection
    try:
        TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
        if TOKEN:
            response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
            if response.status_code != 200:
                logger.warning(f"⚠️ Telegram API warning: Status code {response.status_code}")
                # Log but don't fail just because of temporary API issues
            else:
                # If successful, log bot username as confirmation
                bot_username = response.json().get('result', {}).get('username', 'unknown')
                logger.info(f"✅ Bot connection verified as @{bot_username}")
    except Exception as e:
        logger.warning(f"⚠️ Telegram API ping warning: {e}")
        # Again, don't restart just for API temporary issues

    # Additional checks to verify bot functionality
    try:
        # Check if any bot-related process is running
        result = subprocess.run("ps aux | grep 'python.*bot.py' | grep -v grep | wc -l", 
                               shell=True, capture_output=True, text=True)
        bot_processes = int(result.stdout.strip())
        if bot_processes < 1:
            logger.error("❌ No bot processes found through ps check")
            return False
        else:
            logger.info(f"✅ Found {bot_processes} bot processes running")
    except Exception as process_error:
        logger.warning(f"⚠️ Process check warning: {process_error}")

    # Bot process is running
    return True

def ping_self():
    """Keep the Replit alive by pinging our own server"""
    try:
        # Get deployment URL from environment or compute based on Replit info
        deployment_url = os.environ.get('REPL_SLUG')
        repl_owner = os.environ.get('REPL_OWNER')
        
        # Try different possible Replit URLs
        urls = []
        
        # Add deployment URL if available
        if deployment_url and repl_owner:
            urls = [
                f"https://{deployment_url}.{repl_owner}.repl.co/ping",
                f"https://{deployment_url}-{repl_owner}.replit.app/ping",
                f"https://{deployment_url}.replit.app/ping"
            ]
        
        # Always add localhost as fallback
        urls.append("http://localhost:8080/ping")
                
        # Try each URL
        for try_url in urls:
            try:
                response = requests.get(try_url, timeout=10)
                logger.info(f"💓 Self-ping sent to {try_url}: {response.status_code}")
                return True
            except Exception as e:
                logger.debug(f"Self-ping failed for {try_url}: {e}")
                continue
                
        logger.warning("⚠️ All self-ping attempts failed")
        return False
    except Exception as e:
        logger.warning(f"⚠️ Self-ping error: {e}")
        return False

def main():
    """Main function to keep the bot running forever"""
    global bot_process, shutdown_requested

    logger.info("🤖 Forever process manager starting...")

    # Start the Flask server in a separate thread
    logger.info("🌐 Starting keep-alive server...")
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Print URLs for user reference
    repl_slug = os.environ.get('REPL_SLUG', 'unknown')
    repl_owner = os.environ.get('REPL_OWNER', 'unknown')
    logger.info(f"✅ Keep-alive URLs:")
    logger.info(f"   https://{repl_slug}.{repl_owner}.repl.co")
    logger.info(f"   https://{repl_slug}-{repl_owner}.replit.app")

    # Initial cleanup
    cleanup_environment()

    # Main loop
    consecutive_failures = 0
    last_heartbeat = time.time()
    last_keep_alive = time.time()
    last_self_ping = time.time()

    while not shutdown_requested:
        try:
            current_time = time.time()

            # Send self-ping every 4 minutes
            if current_time - last_self_ping > 240:
                ping_self()
                last_self_ping = current_time

            # Check if bot needs to be restarted
            if not check_bot_health():
                logger.warning("⚠️ Bot not healthy, restarting...")

                # If we've had too many consecutive failures, wait longer
                if consecutive_failures > 5:
                    wait_time = min(300, consecutive_failures * 10)
                    logger.warning(f"⚠️ Too many failures, waiting {wait_time}s...")
                    time.sleep(wait_time)

                # Terminate and clean up
                if bot_process:
                    try:
                        os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
                        time.sleep(2)
                        if bot_process.poll() is None:  # Still running
                            os.killpg(os.getpgid(bot_process.pid), signal.SIGKILL)
                    except:
                        pass

                cleanup_environment()

                # Start the bot
                if start_bot():
                    consecutive_failures = 0
                    last_heartbeat = time.time()
                    logger.info("✅ Bot restarted successfully")
                else:
                    consecutive_failures += 1
                    logger.error(f"❌ Failed to restart bot (failure #{consecutive_failures})")
            else:
                # Bot is healthy
                if consecutive_failures > 0:
                    logger.info("✅ Bot running stably now")
                    consecutive_failures = 0

                # Log health check and heartbeat
                if current_time - last_heartbeat > 60:
                    logger.info("💓 Bot is running properly")
                    last_heartbeat = current_time

            # Sleep before next check
            time.sleep(10)

        except KeyboardInterrupt:
            logger.info("👋 Keyboard interrupt received, shutting down...")
            shutdown_requested = True
        except Exception as e:
            logger.error(f"❌ Error in main loop: {e}")
            logger.error(traceback.format_exc())
            consecutive_failures += 1
            time.sleep(5)

    # Clean shutdown
    if bot_process:
        try:
            os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
        except:
            pass
    logger.info("👋 Forever process manager shutting down...")

if __name__ == "__main__":
    main()
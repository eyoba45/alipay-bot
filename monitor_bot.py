
#!/usr/bin/env python3
"""
Monitor script for keeping the Telegram bot alive 24/7
"""
import os
import sys
import time
import logging
import subprocess
import signal
from datetime import datetime
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

class BotMonitor:
    def __init__(self):
        self.process = None
        self.last_heartbeat = None
        self.restart_count = 0
        self.max_restarts = 50  # Reset counter after this many restarts
        self.restart_interval = 3600  # Reset restart count every hour
        self.last_restart_reset = time.time()
        self.heartbeat_timeout = 300  # 5 minutes
        self.startup_timeout = 30  # 30 seconds for initial startup

    def cleanup_processes(self):
        """Kill any running bot processes"""
        try:
            logger.info("🔍 Checking for running bot processes...")

            # Try multiple cleanup methods to ensure thorough process termination
            cleanup_commands = [
                "ps aux | grep 'python.*bot.py' | grep -v monitor | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true",
                "pkill -9 -f 'python.*bot.py' || true",
                "pkill -f 'telebot' || true"
            ]

            for cmd in cleanup_commands:
                try:
                    subprocess.run(cmd, shell=True, check=False)
                except Exception as e:
                    logger.warning(f"⚠️ Cleanup command failed: {e}")

            # Clean up lock file if it exists
            if os.path.exists("bot_instance.lock"):
                try:
                    os.remove("bot_instance.lock")
                    logger.info("✅ Removed existing lock file")
                except Exception as e:
                    logger.error(f"❌ Error removing lock file: {e}")

            # Clear Telegram webhook
            if self.clear_webhook():
                logger.info("✅ Webhook cleared successfully.")
            else:
                logger.error("❌ Failed to clear webhook.")

            # Wait a moment after cleanup
            time.sleep(2)

        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")

    def clear_webhook(self):
        """Clear any existing webhook"""
        try:
            TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
            if not TOKEN:
                logger.error("❌ TELEGRAM_BOT_TOKEN not found")
                return False

            logger.info("🔄 Clearing Telegram webhook...")
            delete_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook"

            try:
                response = requests.get(delete_url, timeout=10)
                if response.status_code == 200 and response.json().get('ok'):
                    # Also set webhook to empty to ensure it's fully cleared
                    set_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
                    set_response = requests.post(set_url, json={"url": ""}, timeout=10)

                    if set_response.status_code == 200 and set_response.json().get('ok'):
                        logger.info("✅ Successfully cleared webhook")
                        return True

            except Exception as e:
                logger.error(f"❌ Request error: {e}")

            return False
        except Exception as e:
            logger.error(f"❌ Error in clear_webhook: {e}")
            return False

    def start_bot(self):
        """Start the bot process with proper setup"""
        try:
            logger.info("🚀 Starting new bot process...")
            python_path = sys.executable

            # Verify bot.py exists
            if not os.path.exists("bot.py"):
                logger.error("❌ bot.py not found!")
                return False

            # Copy current environment and ensure UTF-8 encoding
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONDONTWRITEBYTECODE'] = '1'  # Prevent .pyc files
            env['PYTHONPATH'] = os.getcwd()  # Ensure imports work

            # Start process with proper monitoring
            self.process = subprocess.Popen(
                [python_path, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                env=env,
                preexec_fn=os.setsid  # Create new process group
            )

            logger.info(f"✅ Bot process started with PID: {self.process.pid}")
            self.last_heartbeat = time.time()

            # Monitor startup
            start_time = time.time()
            while time.time() - start_time < self.startup_timeout:
                if self.process.poll() is not None:
                    out, err = self.process.communicate()
                    logger.error("❌ Bot process failed to start!")
                    if out: logger.error(f"📤 Output: {out.strip()}")
                    if err: logger.error(f"❌ Error: {err.strip()}")
                    return False

                self._read_process_output()
                if self.last_heartbeat > start_time:
                    logger.info("✅ Bot startup successful!")
                    return True

                time.sleep(1)

            logger.warning("⚠️ Bot startup timeout")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to start bot: {e}")
            return False

    def check_process_health(self):
        """Check if the bot process is healthy"""
        if self.process is None:
            logger.warning("⚠️ No bot process found")
            return False

        # Check if process is still running
        if self.process.poll() is not None:
            out, err = self.process.communicate()
            logger.warning("⚠️ Bot process has terminated")
            if out: logger.error(f"📤 Last output: {out.strip()}")
            if err: logger.error(f"❌ Last error: {err.strip()}")
            return False

        # Read process output
        self._read_process_output()

        # Check heartbeat timeout
        if time.time() - self.last_heartbeat > self.heartbeat_timeout:
            logger.warning(f"⚠️ Bot heartbeat timeout (>{self.heartbeat_timeout}s)")
            return False

        return True

    def _read_process_output(self):
        """Read and log process output"""
        try:
            if self.process and self.process.stdout:
                while True:
                    output = self.process.stdout.readline(1024)
                    if not output:
                        break
                    output = output.strip()
                    if output:
                        logger.info(f"📤 Bot: {output}")
                        if "Bot process is running..." in output or "Successfully connected" in output:
                            self.last_heartbeat = time.time()

            if self.process and self.process.stderr:
                while True:
                    error = self.process.stderr.readline(1024)
                    if not error:
                        break
                    error = error.strip()
                    if error:
                        logger.error(f"❌ Bot Error: {error}")

        except Exception as e:
            logger.error(f"❌ Error reading process output: {e}")

    def terminate_process(self):
        """Gracefully terminate the bot process"""
        if not self.process:
            return

        try:
            logger.info("🛑 Terminating bot process...")
            if hasattr(os, 'killpg'):  # Unix-like systems
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            else:  # Windows
                self.process.terminate()

            try:
                self.process.wait(timeout=5)
                logger.info("✅ Bot process terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ Process did not terminate, forcing...")
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait()
                logger.info("✅ Bot process terminated forcefully")
        except Exception as e:
            logger.error(f"❌ Error terminating process: {e}")
        finally:
            self.process = None

    def run(self):
        """Main monitoring loop"""
        consecutive_failures = 0
        last_success = time.time()
        
        while True:
            try:
                # Reset restart count every hour
                if time.time() - self.last_restart_reset > self.restart_interval:
                    self.restart_count = 0
                    self.last_restart_reset = time.time()
                    logger.info("🔄 Reset restart counter")

                # Check if we need to start/restart the bot
                if not self.check_process_health():
                    logger.warning(f"🔄 Restarting bot (attempt {self.restart_count + 1})")

                    # Cleanup before restart
                    self.terminate_process()
                    self.cleanup_processes()

                    # Wait a moment before starting new process
                    time.sleep(2)

                    # Start new process with retries
                    start_success = False
                    for start_attempt in range(3):
                        if self.start_bot():
                            self.restart_count += 1
                            logger.info(f"✅ Bot restarted successfully (attempt {self.restart_count})")
                            consecutive_failures = 0
                            last_success = time.time()
                            start_success = True
                            break
                        else:
                            logger.error(f"❌ Failed to start bot (start attempt {start_attempt + 1}/3)")
                            time.sleep(5 * (start_attempt + 1))  # Progressive delay
                    
                    if not start_success:
                        logger.error("❌ All start attempts failed")
                        consecutive_failures += 1
                        
                        # If we've had multiple consecutive failures, try more drastic measures
                        if consecutive_failures > 3:
                            logger.error(f"⚠️ {consecutive_failures} consecutive failures, performing deep cleanup...")
                            try:
                                # More aggressive cleanup
                                subprocess.run("killall -9 python python3 || true", shell=True)
                                subprocess.run("rm -f *.lock || true", shell=True)
                                time.sleep(5)
                            except Exception as cleanup_err:
                                logger.error(f"❌ Deep cleanup error: {cleanup_err}")
                        
                        time.sleep(10)
                        continue

                    # If too many restarts in a short time, wait longer
                    if self.restart_count >= self.max_restarts:
                        wait_time = min(1800, 30 * self.restart_count)  # Cap at 30 minutes
                        logger.error(f"⚠️ Too many restart attempts ({self.restart_count}), waiting {wait_time}s...")
                        time.sleep(wait_time)
                        self.restart_count = 0
                else:
                    # Bot is healthy
                    consecutive_failures = 0
                    last_success = time.time()

                # Periodic deep verification every hour
                if time.time() - last_success > 3600:
                    logger.warning("⚠️ It's been over an hour since confirmed success, forcing restart...")
                    self.terminate_process()
                    self.cleanup_processes()
                    time.sleep(5)
                    
                    # Force restart with fresh state
                    if self.start_bot():
                        logger.info("✅ Hourly verification restart successful")
                        last_success = time.time()
                    
                # Log heartbeat
                logger.info("💓 Monitor heartbeat - Bot is running")
                time.sleep(10)

            except KeyboardInterrupt:
                logger.info("👋 Shutting down bot monitor...")
                self.terminate_process()
                return
            except Exception as e:
                logger.error(f"❌ Monitor error: {e}")
                consecutive_failures += 1
                time.sleep(5)

if __name__ == "__main__":
    try:
        logger.info("🤖 Starting bot monitor...")
        monitor = BotMonitor()
        monitor.run()
    except Exception as e:
        logger.error(f"❌ Fatal error in monitor: {e}")
        sys.exit(1)

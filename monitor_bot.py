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
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logs
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot_monitor.log')
    ]
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
        self.startup_timeout = 60  # Increased timeout for initial startup

    def wait_for_keep_alive(self, timeout=30):
        """Wait for keep-alive server to be ready"""
        start_time = time.time()
        logger.info("Waiting for keep-alive server to start...")
        while time.time() - start_time < timeout:
            try:
                response = requests.get('http://localhost:8080/ping', timeout=5)
                if response.status_code == 200 and response.text == 'pong':
                    logger.info("✅ Keep-alive server is responding")
                    return True
            except requests.RequestException:
                time.sleep(1)
        logger.error("❌ Keep-alive server failed to respond")
        return False

    def cleanup_processes(self):
        """Kill any running bot processes"""
        try:
            logger.info("🔍 Checking for running bot processes...")
            cleanup_commands = [
                "pkill -f 'python.*bot.py' || true",
                "pkill -f 'telebot' || true"
            ]

            for cmd in cleanup_commands:
                try:
                    subprocess.run(cmd, shell=True, check=False)
                except Exception as e:
                    logger.warning(f"⚠️ Cleanup command failed: {e}")

            # Clean up lock files
            lock_files = ['bot_instance.lock', 'keep_alive.lock']
            for lock_file in lock_files:
                if os.path.exists(lock_file):
                    try:
                        os.remove(lock_file)
                        logger.info(f"✅ Removed {lock_file}")
                    except Exception as e:
                        logger.error(f"❌ Error removing {lock_file}: {e}")

            time.sleep(2)  # Wait for processes to fully terminate
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
            try:
                delete_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"
                response = requests.get(delete_url, timeout=10)
                if response.status_code == 200 and response.json().get('ok'):
                    logger.info("✅ Successfully cleared webhook")
                    return True
            except Exception as e:
                logger.error(f"❌ Webhook error: {e}")

            return False
        except Exception as e:
            logger.error(f"❌ Error in clear_webhook: {e}")
            return False

    def start_bot(self):
        """Start the bot process"""
        try:
            logger.info("🚀 Starting new bot process...")

            # Verify bot.py exists
            if not os.path.exists("bot.py"):
                logger.error("❌ bot.py not found!")
                return False

            # Set up environment
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env['PYTHONPATH'] = os.getcwd()

            # Start process
            self.process = subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                env=env,
                start_new_session=True
            )

            logger.info(f"✅ Bot process started with PID: {self.process.pid}")
            self.last_heartbeat = time.time()

            # Monitor startup with retries
            startup_verified = False
            start_time = time.time()
            startup_attempts = 0
            max_startup_attempts = 3

            while time.time() - start_time < self.startup_timeout and startup_attempts < max_startup_attempts:
                if self.process.poll() is not None:
                    out, err = self.process.communicate()
                    logger.error("❌ Bot process failed to start!")
                    if out: logger.error(f"📤 Output: {out.strip()}")
                    if err: logger.error(f"❌ Error: {err.strip()}")
                    return False

                # Check process output
                output = self._read_process_output()
                if output:
                    logger.debug(f"Startup output: {output}")
                    if any(msg in output for msg in ["Keep-alive check passed", "Successfully connected", "Bot process is running"]):
                        startup_verified = True
                        logger.info("✅ Bot startup successful!")
                        break

                time.sleep(2)
                startup_attempts += 1

            if not startup_verified:
                logger.warning("⚠️ Bot startup verification incomplete")
                return False

            return True

        except Exception as e:
            logger.error(f"❌ Failed to start bot: {e}")
            return False

    def check_process_health(self):
        """Check if bot process is healthy"""
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

        # Check keep-alive server
        try:
            response = requests.get('http://localhost:8080/ping', timeout=5)
            if response.status_code != 200 or response.text != 'pong':
                logger.warning("⚠️ Keep-alive server not responding correctly")
                return False
        except requests.RequestException:
            logger.warning("⚠️ Keep-alive server not accessible")
            return False

        # Read process output
        output = self._read_process_output()
        if output:
            logger.debug(f"Health check output: {output}")

        # Check heartbeat timeout
        if time.time() - self.last_heartbeat > self.heartbeat_timeout:
            logger.warning(f"⚠️ Bot heartbeat timeout (>{self.heartbeat_timeout}s)")
            return False

        return True

    def _read_process_output(self):
        """Read process output"""
        output_buffer = []
        try:
            if self.process and self.process.stdout:
                while True:
                    output = self.process.stdout.readline(1024)
                    if not output:
                        break
                    output = output.strip()
                    if output:
                        logger.info(f"📤 Bot: {output}")
                        output_buffer.append(output)
                        if any(msg in output for msg in ["Bot process is running", "Keep-alive check passed", "Successfully connected"]):
                            self.last_heartbeat = time.time()

            if self.process and self.process.stderr:
                while True:
                    error = self.process.stderr.readline(1024)
                    if not error:
                        break
                    error = error.strip()
                    if error:
                        logger.error(f"❌ Bot Error: {error}")
                        output_buffer.append(f"ERROR: {error}")

        except Exception as e:
            logger.error(f"❌ Error reading process output: {e}")

        return '\n'.join(output_buffer)

    def terminate_process(self):
        """Terminate the bot process"""
        if not self.process:
            return

        try:
            logger.info("🛑 Terminating bot process...")
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
                logger.info("✅ Bot process terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ Process did not terminate, forcing...")
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
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

                if not self.check_process_health():
                    logger.warning(f"🔄 Restarting bot (attempt {self.restart_count + 1})")

                    self.terminate_process()
                    self.cleanup_processes()
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
                            time.sleep(5 * (start_attempt + 1))

                    if not start_success:
                        logger.error("❌ All start attempts failed")
                        consecutive_failures += 1

                        if consecutive_failures > 3:
                            logger.error(f"⚠️ {consecutive_failures} consecutive failures")
                            try:
                                subprocess.run("killall -9 python python3 || true", shell=True)
                                subprocess.run("rm -f *.lock || true", shell=True)
                                time.sleep(5)
                            except Exception as cleanup_err:
                                logger.error(f"❌ Deep cleanup error: {cleanup_err}")

                        time.sleep(10)
                        continue

                    if self.restart_count >= self.max_restarts:
                        wait_time = min(1800, 30 * self.restart_count)
                        logger.error(f"⚠️ Too many restart attempts ({self.restart_count}), waiting {wait_time}s...")
                        time.sleep(wait_time)
                        self.restart_count = 0
                else:
                    consecutive_failures = 0
                    last_success = time.time()

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

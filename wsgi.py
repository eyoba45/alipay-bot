
import os
import sys
import logging

# Add the current directory to the path
path = os.path.dirname(os.path.abspath(__file__))
if path not in sys.path:
    sys.path.insert(0, path)

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import the Flask app and other dependencies
from keep_alive import app as application

# Start the bot in a separate process if running via WSGI
if __name__ != "__main__":
    import threading
    import subprocess
    
    def run_bot():
        try:
            logger.info("Starting Telegram bot via WSGI...")
            subprocess.Popen(
                [sys.executable, "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
    
    # Start bot in a thread to not block WSGI application
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()

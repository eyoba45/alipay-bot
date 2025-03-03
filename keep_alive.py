
#!/usr/bin/env python3
"""
Keep-alive server to prevent the bot from being terminated due to inactivity
"""
import os
import sys
import time
import logging
from threading import Thread
from flask import Flask, request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Disable Flask's default logging
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.WARNING)

# Create Flask app
app = Flask(__name__)

# Health check timestamp
last_health_check = time.time()

@app.route('/')
def home():
    """Home endpoint"""
    return "Bot is running! Server is active."

@app.route('/ping')
def ping():
    """Simple ping endpoint for health checks"""
    global last_health_check
    last_health_check = time.time()
    return "pong"

@app.route('/health')
def health():
    """Health check endpoint"""
    uptime = time.time() - last_health_check
    if uptime > 300:  # 5 minutes
        return f"Warning: No health check in {uptime:.1f} seconds", 200
    return f"Healthy! Last check: {uptime:.1f} seconds ago", 200

def run_server():
    """Run the Flask server"""
    try:
        # Use PORT from environment variable or default to 8080
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Server error: {e}")

def start_server_thread():
    """Start the server in a separate thread"""
    server_thread = Thread(target=run_server)
    server_thread.daemon = True  # Thread will exit when main thread exits
    server_thread.start()
    logger.info(f"Keep-alive server started on port {os.environ.get('PORT', 8080)}")
    return server_thread

def keep_alive():
    """Start the keep-alive server and return"""
    logger.info("Starting keep-alive server...")
    start_server_thread()
    logger.info("Keep-alive server started")

if __name__ == "__main__":
    logger.info("Keep-alive server starting...")
    try:
        # Run the server in the main thread if script is called directly
        keep_alive()
        # Keep script running
        while True:
            time.sleep(60)
            logger.info("Keep-alive server is running")
    except KeyboardInterrupt:
        logger.info("Keep-alive server stopped by user")
    except Exception as e:
        logger.error(f"Error in keep-alive server: {e}")
        sys.exit(1)

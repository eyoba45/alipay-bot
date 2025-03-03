
#!/usr/bin/env python3
"""
Script to monitor Telegram bot performance and responsiveness
"""
import os
import logging
import sys
import time
import requests
import threading
import statistics
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN not found!")
    sys.exit(1)

# Performance metrics
class BotPerformanceMonitor:
    def __init__(self):
        self.api_response_times = []
        self.max_samples = 100
        self.last_check = datetime.now()
        self.connection_failures = 0
        self.lock = threading.Lock()
        
    def record_api_response(self, response_time):
        with self.lock:
            self.api_response_times.append(response_time)
            if len(self.api_response_times) > self.max_samples:
                self.api_response_times.pop(0)
    
    def record_failure(self):
        with self.lock:
            self.connection_failures += 1
            
    def reset_failures(self):
        with self.lock:
            self.connection_failures = 0
            
    def get_average_response_time(self):
        with self.lock:
            if not self.api_response_times:
                return None
            return statistics.mean(self.api_response_times)
    
    def get_metrics_report(self):
        with self.lock:
            if not self.api_response_times:
                return "No API response data available"
                
            avg_time = statistics.mean(self.api_response_times)
            max_time = max(self.api_response_times)
            min_time = min(self.api_response_times)
            
            if len(self.api_response_times) >= 2:
                std_dev = statistics.stdev(self.api_response_times)
            else:
                std_dev = 0
                
            return (f"API Performance Metrics:\n"
                   f"- Average response time: {avg_time:.2f}s\n"
                   f"- Maximum response time: {max_time:.2f}s\n"
                   f"- Minimum response time: {min_time:.2f}s\n"
                   f"- Standard deviation: {std_dev:.2f}s\n"
                   f"- Connection failures: {self.connection_failures}\n"
                   f"- Samples collected: {len(self.api_response_times)}")

# Initialize monitor
monitor = BotPerformanceMonitor()

def check_bot_api_health():
    """Test the Telegram Bot API response time"""
    try:
        start_time = time.time()
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
        elapsed = time.time() - start_time
        
        monitor.record_api_response(elapsed)
        
        if response.status_code == 200:
            bot_info = response.json().get('result', {})
            logger.info(f"✅ Bot connection verified as @{bot_info.get('username')} (API Response: {elapsed:.2f}s)")
            monitor.reset_failures()
            return True
        else:
            logger.error(f"❌ API error: Status code {response.status_code} (Response: {elapsed:.2f}s)")
            monitor.record_failure()
            return False
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ API connection error: {e} (Attempted: {elapsed:.2f}s)")
        monitor.record_failure()
        return False

def monitor_api_continuously():
    """Monitor API health continuously"""
    check_interval = 60  # seconds
    
    while True:
        try:
            check_bot_api_health()
            
            # Log detailed metrics every 10 checks
            if datetime.now() - monitor.last_check > timedelta(minutes=10):
                logger.info(monitor.get_metrics_report())
                monitor.last_check = datetime.now()
                
        except Exception as e:
            logger.error(f"Error in monitoring thread: {e}")
        
        time.sleep(check_interval)

if __name__ == "__main__":
    logger.info("Starting Telegram Bot API performance monitor")
    monitor_api_continuously()

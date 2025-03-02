
#!/usr/bin/env python3
"""
Telegram Bot Uptime Monitoring Script

This script periodically tests if the bot is running and logs the results.
Run this in a separate process to track uptime.
"""
import os
import sys
import time
import logging
import requests
import json
from datetime import datetime
import sqlite3

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

# Create uptime database if it doesn't exist
def init_uptime_db():
    """Initialize the uptime database"""
    conn = sqlite3.connect('bot_uptime.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS uptime_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        status TEXT,
        response_time REAL,
        error_message TEXT
    )
    ''')
    conn.commit()
    conn.close()

def log_check(status, response_time=0, error_message=None):
    """Log a check to the database"""
    conn = sqlite3.connect('bot_uptime.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO uptime_checks (timestamp, status, response_time, error_message) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), status, response_time, error_message)
    )
    conn.commit()
    conn.close()

def check_bot_running():
    """Check if the bot is running by testing the Telegram API connection"""
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
        log_check("ERROR", error_message="TELEGRAM_BOT_TOKEN not found")
        return False
        
    try:
        # Test getMe endpoint
        start_time = time.time()
        me_url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        me_response = requests.get(me_url, timeout=10)
        response_time = time.time() - start_time
        
        if me_response.status_code == 200 and me_response.json().get('ok'):
            bot_info = me_response.json().get('result', {})
            logger.info(f"✅ Bot is running! Connected as @{bot_info.get('username')} in {response_time:.2f}s")
            log_check("OK", response_time)
            return True
        else:
            logger.error(f"❌ Bot check failed: {me_response.status_code} - {me_response.text}")
            log_check("FAIL", response_time, f"API returned: {me_response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Error checking bot status: {e}")
        log_check("ERROR", error_message=str(e))
        return False

def check_process_running():
    """Check if the bot process is running"""
    try:
        import subprocess
        # Look for python processes running bot.py
        result = subprocess.run(
            "ps aux | grep 'python.*bot.py' | grep -v grep | wc -l", 
            shell=True, 
            capture_output=True, 
            text=True
        )
        count = int(result.stdout.strip())
        if count > 0:
            logger.info(f"✅ Bot process check: {count} bot processes running")
            return True
        else:
            logger.warning("⚠️ No bot processes found running")
            return False
    except Exception as e:
        logger.error(f"❌ Error checking bot process: {e}")
        return False

def generate_uptime_report():
    """Generate an uptime report based on the database"""
    try:
        conn = sqlite3.connect('bot_uptime.db')
        cursor = conn.cursor()
        
        # Get total checks
        cursor.execute("SELECT COUNT(*) FROM uptime_checks")
        total_checks = cursor.fetchone()[0]
        
        # Get successful checks
        cursor.execute("SELECT COUNT(*) FROM uptime_checks WHERE status = 'OK'")
        successful_checks = cursor.fetchone()[0]
        
        # Calculate uptime percentage
        uptime_percentage = (successful_checks / total_checks) * 100 if total_checks > 0 else 0
        
        # Get average response time
        cursor.execute("SELECT AVG(response_time) FROM uptime_checks WHERE status = 'OK'")
        avg_response_time = cursor.fetchone()[0] or 0
        
        # Get the most recent downtime
        cursor.execute(
            "SELECT timestamp, error_message FROM uptime_checks WHERE status != 'OK' ORDER BY timestamp DESC LIMIT 1"
        )
        last_downtime = cursor.fetchone()
        
        conn.close()
        
        # Print report
        logger.info("=== BOT UPTIME REPORT ===")
        logger.info(f"Total checks: {total_checks}")
        logger.info(f"Uptime: {uptime_percentage:.2f}%")
        logger.info(f"Average response time: {avg_response_time:.2f}s")
        
        if last_downtime:
            logger.info(f"Last downtime: {last_downtime[0]}")
            logger.info(f"Reason: {last_downtime[1]}")
        else:
            logger.info("No downtime recorded")
            
        logger.info("========================")
        
    except Exception as e:
        logger.error(f"❌ Error generating uptime report: {e}")

def main():
    """Main function"""
    logger.info("🤖 Starting bot uptime monitor")
    init_uptime_db()
    
    # Check interval in seconds (5 minutes)
    check_interval = 300
    report_interval = 24 * 60 * 60  # Generate report every 24 hours
    
    last_report_time = time.time()
    
    try:
        while True:
            check_bot_running()
            check_process_running()
            
            # Generate daily report
            current_time = time.time()
            if current_time - last_report_time >= report_interval:
                generate_uptime_report()
                last_report_time = current_time
            
            logger.info(f"Sleeping for {check_interval} seconds...")
            time.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("Uptime monitor stopped by user")
        generate_uptime_report()
    except Exception as e:
        logger.error(f"Unexpected error in uptime monitor: {e}")
        
if __name__ == "__main__":
    main()

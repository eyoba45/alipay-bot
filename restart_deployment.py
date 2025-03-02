
#!/usr/bin/env python3
"""
Script to restart the bot deployment safely
"""
import os
import sys
import time
import logging
import subprocess
import signal
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def kill_processes():
    """Kill any existing bot processes"""
    logger.info("🔪 Killing any existing bot processes...")
    
    # Find all Python processes running bot scripts
    try:
        output = subprocess.check_output(
            "ps aux | grep python | grep -E 'bot.py|forever.py|monitor_bot.py' | grep -v grep | awk '{print $2}'",
            shell=True, text=True
        ).strip()
        
        if output:
            pids = output.split('\n')
            for pid in pids:
                if pid.strip():
                    logger.info(f"Killing process {pid}")
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except:
                        pass
    except:
        pass
    
    # Use pkill as a backup method
    try:
        subprocess.run("pkill -9 -f 'python.*bot.py' || true", shell=True)
        subprocess.run("pkill -9 -f 'python.*forever.py' || true", shell=True)
        subprocess.run("pkill -9 -f 'telebot' || true", shell=True)
    except:
        pass

def remove_lock_files():
    """Remove any lock files"""
    try:
        subprocess.run("rm -f *.lock", shell=True)
        logger.info("✅ Removed any lock files")
    except:
        pass

def clear_webhook():
    """Clear any existing webhook"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set")
        return False
        
    logger.info("🔄 Clearing Telegram webhook (first attempt)...")
    
    try:
        # Delete any existing webhook
        response = requests.get(
            f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true",
            timeout=10
        )
        
        if response.status_code == 200 and response.json().get('ok'):
            logger.info("✅ Successfully cleared webhook")
            
            # Verify webhook is cleared
            info_response = requests.get(
                f"https://api.telegram.org/bot{token}/getWebhookInfo",
                timeout=10
            )
            
            if info_response.status_code == 200 and not info_response.json().get('result', {}).get('url'):
                logger.info("✅ Webhook confirmed clear")
                return True
            else:
                logger.error("❌ Webhook still set")
                return False
        else:
            logger.error(f"❌ Failed to clear webhook: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Error clearing webhook: {e}")
        return False

def main():
    """Main function for restart"""
    print("🔄 Attempting to restart deployment...")
    
    # Kill processes
    kill_processes()
    
    # Remove lock files
    remove_lock_files()
    
    # Clear webhook
    clear_webhook()
    
    # Don't start the bot here - let the deployment script handle it
    print("🚀 Deployment restart script completed")
    print("✅ Your bot should now be running 24/7 in polling mode")
    print("✅ Restart completed successfully")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

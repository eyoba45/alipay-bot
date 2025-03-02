
#!/usr/bin/env python3
"""
Clean locks and reset environment for bot deployment
"""
import os
import sys
import time
import logging
import subprocess
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def cleanup_processes():
    """Kill any existing bot processes"""
    try:
        logger.info("🔍 Checking for running bot processes...")
        
        # Use multiple commands to ensure thorough cleanup
        cleanup_commands = [
            "ps aux | grep 'python.*bot.py' | grep -v grep | awk '{print $2}' | xargs kill -9 2>/dev/null || true",
            "pkill -9 -f 'python.*bot.py' || true",
            "pkill -f 'telebot' || true"
        ]
        
        for cmd in cleanup_commands:
            try:
                result = subprocess.run(cmd, shell=True, check=False)
                logger.warning(f"⚠️ Process cleanup returned non-zero exit code: {result.returncode}")
            except Exception as e:
                logger.error(f"❌ Error during process cleanup: {e}")
        
        # Clean up lock file if it exists
        if os.path.exists("bot_instance.lock"):
            try:
                os.remove("bot_instance.lock")
                logger.info("✅ Removed existing lock file")
            except Exception as e:
                logger.error(f"❌ Error removing lock file: {e}")
    
    except Exception as e:
        logger.error(f"❌ Error cleaning up processes: {e}")
        return False
    
    return True

def clear_webhook():
    """Clear Telegram webhook with verification"""
    try:
        logger.info("🔄 Clearing Telegram webhook...")
        TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
        
        if not TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
            return False
        
        # First try - delete webhook
        try:
            delete_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"
            response = requests.get(delete_url, timeout=10)
            
            if response.status_code == 200 and response.json().get('ok'):
                logger.info("✅ Successfully deleted webhook")
            else:
                logger.error(f"❌ Failed to delete webhook: {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Error deleting webhook: {e}")
            return False
        
        # Second try - set empty webhook
        try:
            set_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
            response = requests.post(set_url, json={"url": ""}, timeout=10)
            
            if response.status_code == 200 and response.json().get('ok'):
                logger.info("✅ Successfully reset webhook to empty")
            else:
                logger.error(f"❌ Failed to set empty webhook: {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Error setting empty webhook: {e}")
            return False
        
        # Verify webhook status
        try:
            info_url = f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
            response = requests.get(info_url, timeout=10)
            webhook_info = response.json()
            logger.info(f"📊 Current webhook status: {webhook_info}")
            
            if response.status_code == 200 and not webhook_info.get('result', {}).get('url'):
                logger.info("✅ Webhook cleared successfully.")
                return True
            else:
                logger.warning(f"⚠️ Webhook may still be active: {webhook_info}")
                return False
        except Exception as e:
            logger.error(f"❌ Error getting webhook info: {e}")
            return False
    
    except Exception as e:
        logger.error(f"❌ Error in clear_webhook: {e}")
        return False

def main():
    """Main function"""
    try:
        print("🧹 Starting cleanup process...")
        
        # Clean up processes
        cleanup_processes()
        
        # Clear webhook
        if clear_webhook():
            print("✅ Webhook cleared successfully.")
        else:
            print("⚠️ Issues clearing webhook.")
        
        print("✨ Environment is clean and ready to start a new bot instance")
        return 0
    
    except Exception as e:
        logger.error(f"❌ Fatal error in cleanup: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())

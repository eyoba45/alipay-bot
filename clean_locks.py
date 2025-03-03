
#!/usr/bin/env python3
"""
Script to clean Telegram bot locks (409 Conflict errors)
"""
import os
import logging
import sys
import requests
import time

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

def clean_webhook():
    """Delete any existing webhook"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"
        response = requests.get(url)
        if response.status_code == 200:
            logger.info("✅ Webhook deleted successfully")
            return True
        else:
            logger.error(f"❌ Failed to delete webhook: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Error deleting webhook: {e}")
        return False

def get_updates_with_timeout():
    """Get updates with timeout to clear queue"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1&timeout=1&limit=1"
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            logger.info("✅ GetUpdates called successfully")
            return True
        else:
            logger.error(f"❌ Failed to get updates: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Error getting updates: {e}")
        return False

def main():
    """Main function"""
    logger.info("🧹 Starting cleanup process...")

    # Delete webhook
    if clean_webhook():
        logger.info("✅ Webhook cleanup successful")
    else:
        logger.error("❌ Webhook cleanup failed")

    # Wait a bit
    time.sleep(1)

    # Clear update queue
    if get_updates_with_timeout():
        logger.info("✅ Update queue cleared")
    else:
        logger.error("❌ Failed to clear update queue")

    # Final confirmation
    logger.info("✅ Cleanup process completed. Restart your bot now.")

if __name__ == "__main__":
    main()


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
#!/usr/bin/env python3
"""
Script to clean up stale lock files that might cause issues
"""
import os
import logging
import sys
import time
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def clean_lock_files():
    """Find and clean up stale lock files"""
    lock_files = [f for f in os.listdir('.') if f.endswith('.lock')]
    
    for lock_file in lock_files:
        try:
            # Check file age
            file_stat = os.stat(lock_file)
            file_age_seconds = time.time() - file_stat.st_mtime
            
            # If older than 10 minutes, consider it stale
            if file_age_seconds > 600:
                logger.warning(f"🧹 Removing stale lock file: {lock_file} (age: {file_age_seconds:.1f}s)")
                os.remove(lock_file)
            else:
                logger.info(f"🔍 Recent lock file: {lock_file} (age: {file_age_seconds:.1f}s)")
        except Exception as e:
            logger.error(f"❌ Error processing lock file {lock_file}: {e}")

if __name__ == "__main__":
    logger.info("🔒 Starting lock file cleanup")
    clean_lock_files()
    logger.info("✅ Lock file cleanup completed")

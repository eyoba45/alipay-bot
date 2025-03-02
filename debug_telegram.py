
#!/usr/bin/env python3
"""
Diagnostic script for troubleshooting Telegram API issues
"""
import os
import sys
import requests
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_telegram_connection():
    """Test connection to Telegram API"""
    try:
        TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not TOKEN:
            logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
            return False
            
        logger.info(f"🔑 Found bot token: {TOKEN[:5]}...{TOKEN[-5:]}")
        
        # Test getMe endpoint
        logger.info("🔍 Testing getMe endpoint...")
        me_url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        me_response = requests.get(me_url, timeout=10)
        logger.info(f"Response code: {me_response.status_code}")
        logger.info(f"Response body: {me_response.text}")
        
        if me_response.status_code != 200:
            logger.error("❌ getMe request failed")
            return False
            
        # Try setting webhook to empty (to ensure polling mode)
        logger.info("🔄 Clearing any webhook...")
        webhook_url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true"
        webhook_response = requests.get(webhook_url, timeout=10)
        logger.info(f"Webhook clear response: {webhook_response.status_code}")
        logger.info(f"Response body: {webhook_response.text}")
        
        if webhook_response.status_code != 200:
            logger.error("❌ Failed to clear webhook")
        
        return True
    except Exception as e:
        logger.error(f"❌ Error testing Telegram connection: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    print("🤖 Telegram API Diagnostic Tool")
    print("===============================")
    success = test_telegram_connection()
    print(f"\nDiagnostic completed: {'✅ Success' if success else '❌ Failed'}")

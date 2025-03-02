
#!/usr/bin/env python3
"""
Test environment variables and Telegram connectivity
"""
import os
import sys
import logging
import requests
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_environment():
    """Test all required environment variables"""
    required_vars = ['TELEGRAM_BOT_TOKEN', 'ADMIN_CHAT_ID', 'DATABASE_URL']
    missing_vars = []
    
    print("\n=== ENVIRONMENT VARIABLE CHECK ===")
    
    for var in required_vars:
        value = os.environ.get(var)
        if not value:
            print(f"❌ {var}: MISSING")
            missing_vars.append(var)
        else:
            # Mask sensitive information
            masked_value = value[:5] + "..." + value[-5:] if len(value) > 10 else "***"
            print(f"✅ {var}: {masked_value}")
    
    if missing_vars:
        print(f"\n⚠️ MISSING VARIABLES: {', '.join(missing_vars)}")
        print("\nPlease add these variables to your Replit Secrets:")
        for var in missing_vars:
            print(f"- {var}")
        return False
    
    print("\n✅ All required environment variables are set!")
    return True

def test_telegram_connection():
    """Test connection to Telegram API"""
    print("\n=== TELEGRAM API CONNECTION TEST ===")
    
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("❌ Cannot test Telegram API: TELEGRAM_BOT_TOKEN is missing")
        return False
    
    try:
        print(f"🔍 Testing connection to Telegram API...")
        start_time = time.time()
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                bot_info = data.get('result', {})
                print(f"✅ Successfully connected to Telegram API in {elapsed:.2f}s")
                print(f"✅ Bot username: @{bot_info.get('username')}")
                print(f"✅ Bot ID: {bot_info.get('id')}")
                return True
            else:
                print(f"❌ Telegram API returned error: {data}")
        else:
            print(f"❌ Failed to connect to Telegram API: HTTP {response.status_code}")
            print(f"Response: {response.text}")
        
        return False
    except Exception as e:
        print(f"❌ Error connecting to Telegram API: {e}")
        return False

def clear_webhook():
    """Clear any existing webhook"""
    print("\n=== WEBHOOK CLEANUP ===")
    
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("❌ Cannot clear webhook: TELEGRAM_BOT_TOKEN is missing")
        return False
    
    try:
        print("🔄 Clearing Telegram webhook...")
        response = requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=true", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                print("✅ Webhook cleared successfully")
                
                # Verify webhook is actually cleared
                time.sleep(1)
                verify_response = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=10)
                if verify_response.status_code == 200:
                    webhook_data = verify_response.json()
                    if webhook_data.get('ok') and not webhook_data.get('result', {}).get('url'):
                        print("✅ Webhook confirmed clear")
                    else:
                        print(f"⚠️ Webhook might still be set: {webhook_data}")
                return True
            else:
                print(f"❌ Telegram API returned error: {data}")
        else:
            print(f"❌ Failed to clear webhook: HTTP {response.status_code}")
            print(f"Response: {response.text}")
        
        return False
    except Exception as e:
        print(f"❌ Error clearing webhook: {e}")
        return False

if __name__ == "__main__":
    print("🔍 Running environment and Telegram API tests...")
    
    env_ok = test_environment()
    api_ok = test_telegram_connection()
    webhook_ok = clear_webhook()
    
    print("\n=== TEST SUMMARY ===")
    print(f"Environment variables: {'✅ OK' if env_ok else '❌ FAILED'}")
    print(f"Telegram API connection: {'✅ OK' if api_ok else '❌ FAILED'}")
    print(f"Webhook clearance: {'✅ OK' if webhook_ok else '❌ FAILED'}")
    
    if not env_ok or not api_ok or not webhook_ok:
        print("\n⚠️ Some tests failed! Please fix the issues above before running the bot.")
        sys.exit(1)
    else:
        print("\n✅ All tests passed! Your environment is ready to run the bot.")
        sys.exit(0)

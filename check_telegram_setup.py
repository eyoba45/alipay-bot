
#!/usr/bin/env python3
"""
Verify Telegram API token and environment setup
"""
import os
import sys
import time
import logging
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def check_environment_variables():
    """Check all required environment variables"""
    required_vars = {
        'TELEGRAM_BOT_TOKEN': os.environ.get('TELEGRAM_BOT_TOKEN'),
        'ADMIN_CHAT_ID': os.environ.get('ADMIN_CHAT_ID'),
        'DATABASE_URL': os.environ.get('DATABASE_URL')
    }
    
    print("=== ENVIRONMENT VARIABLE CHECK ===")
    all_set = True
    
    for name, value in required_vars.items():
        if value:
            # Show only partial token/url for security
            display_value = value
            if name == 'TELEGRAM_BOT_TOKEN' and len(value) > 10:
                display_value = value[:5] + '...' + value[-5:]
            elif name == 'ADMIN_CHAT_ID':
                display_value = '***'
            elif name == 'DATABASE_URL' and len(value) > 10:
                display_value = value[:5] + '...' + value[-7:]
                
            print(f"✅ {name}: {display_value}")
        else:
            print(f"❌ {name}: Not set")
            all_set = False
    
    if all_set:
        print("\n✅ All required environment variables are set!")
    else:
        print("\n❌ Some environment variables are missing!")
    
    return all_set

def test_telegram_connection():
    """Test connection to Telegram API"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return False
        
    print("\n=== TELEGRAM API CONNECTION TEST ===")
    print("🔍 Testing connection to Telegram API...")
    
    try:
        start_time = time.time()
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10
        )
        elapsed = time.time() - start_time
        
        if response.status_code == 200 and response.json().get('ok'):
            bot_info = response.json().get('result', {})
            print(f"✅ Successfully connected to Telegram API in {elapsed:.2f}s")
            print(f"✅ Bot username: @{bot_info.get('username')}")
            print(f"✅ Bot ID: {bot_info.get('id')}")
            return True
        else:
            print(f"❌ Failed to connect to Telegram API: {response.status_code}")
            print(f"❌ Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error connecting to Telegram API: {e}")
        return False

def clear_webhook():
    """Clear any existing webhook"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return False
        
    print("\n=== WEBHOOK CLEANUP ===")
    print("🔄 Clearing Telegram webhook...")
    
    try:
        # Delete any existing webhook
        response = requests.get(
            f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true",
            timeout=10
        )
        
        if response.status_code == 200 and response.json().get('ok'):
            print("✅ Webhook cleared successfully")
            
            # Verify webhook is cleared
            info_response = requests.get(
                f"https://api.telegram.org/bot{token}/getWebhookInfo",
                timeout=10
            )
            
            if info_response.status_code == 200 and not info_response.json().get('result', {}).get('url'):
                print("✅ Webhook confirmed clear")
                return True
            else:
                print("❌ Webhook still set")
                return False
        else:
            print(f"❌ Failed to clear webhook: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error clearing webhook: {e}")
        return False

def main():
    """Main function"""
    print("🔍 Running environment and Telegram API tests...\n")
    
    env_ok = check_environment_variables()
    api_ok = test_telegram_connection()
    webhook_ok = clear_webhook()
    
    print("\n=== TEST SUMMARY ===")
    print(f"Environment variables: {'✅ OK' if env_ok else '❌ FAIL'}")
    print(f"Telegram API connection: {'✅ OK' if api_ok else '❌ FAIL'}")
    print(f"Webhook clearance: {'✅ OK' if webhook_ok else '❌ FAIL'}")
    
    if env_ok and api_ok and webhook_ok:
        print("\n✅ All tests passed! Your environment is ready to run the bot.")
        return 0
    else:
        print("\n❌ Some tests failed. Please fix the issues before running the bot.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

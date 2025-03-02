import os
import logging
import sys
import telebot

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_bot_token():
    """Test if the bot token is valid and working"""
    try:
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:
            print("❌ Error: TELEGRAM_BOT_TOKEN is not set!")
            return False
            
        print("🔑 Found bot token, testing connection...")
        bot = telebot.TeleBot(token)
        
        # Try to get bot information
        bot_info = bot.get_me()
        print(f"✅ Successfully connected to Telegram as @{bot_info.username}")
        print(f"Bot ID: {bot_info.id}")
        print(f"Bot Name: {bot_info.first_name}")
        return True
        
    except Exception as e:
        print(f"❌ Error testing bot token: {str(e)}")
        return False

if __name__ == "__main__":
    print("🤖 Testing Telegram Bot Token...")
    success = test_bot_token()
    if not success:
        sys.exit(1)


#!/usr/bin/env python3
"""
Test script to verify bot functionality, with special testing for welcome animation
"""
import os
import sys
import logging
import telebot
import time
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_welcome_animation():
    """Test the welcome animation module directly"""
    print("\n🎬 Testing Welcome Animation Module...")
    
    try:
        # Try to import the welcome animation module
        from welcome_animation import send_personalized_welcome, BOT_PERSONALITY
        
        print("✅ Successfully imported welcome_animation module")
        print(f"🤖 Bot personality definition found with {len(BOT_PERSONALITY['traits'])} traits")
        print(f"🔖 Available slogans: {len(BOT_PERSONALITY['slogans'])}")
        print(f"👋 Available greetings: {len(BOT_PERSONALITY['greetings'])}")
        
        # Create a bot instance to test the animation
        TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not TOKEN:
            print("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
            return False
            
        bot = telebot.TeleBot(TOKEN)
        
        # Ask for chat_id to test with
        print("\n⚠️ This will send test messages to a real user!")
        print("Enter a chat ID to test the welcome animation with:")
        print("(Leave blank and press Enter to skip this test)")
        
        chat_id_input = input("Chat ID: ")
        if chat_id_input.strip():
            chat_id = int(chat_id_input)
            print(f"🚀 Testing welcome animation with chat_id: {chat_id}")
            
            # Call the animation function
            result = send_personalized_welcome(bot, chat_id, {'name': 'Test User'})
            if result:
                print("✅ Welcome animation test completed successfully!")
            else:
                print("❌ Welcome animation test failed to send message")
                
        return True
        
    except ImportError:
        print("❌ Could not import welcome_animation module")
        return False
    except Exception as e:
        print(f"❌ Error testing welcome animation: {e}")
        print(traceback.format_exc())
        return False

def test_bot_startup():
    """Test if the bot can connect to Telegram API"""
    print("🔍 Testing bot connection to Telegram...")
    
    # Check if token exists
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not found in environment variables")
        return False
    
    try:
        # Create bot instance
        bot = telebot.TeleBot(TOKEN)
        
        # Try to get bot info
        print("📡 Connecting to Telegram API...")
        bot_info = bot.get_me()
        
        print(f"✅ Successfully connected to Telegram as @{bot_info.username}")
        print(f"Bot ID: {bot_info.id}")
        print(f"Bot Name: {bot_info.first_name}")
        
        # First test welcome animation
        test_welcome_animation()
        
        # Try short polling to verify further functionality
        print("\n⏱️ Testing polling for 5 seconds to verify bot functionality...")
        print("Press Ctrl+C to stop polling test early if it's working")
        
        @bot.message_handler(func=lambda msg: True)
        def echo_all(message):
            bot.reply_to(message, "Test bot is working!")
        
        bot.polling(none_stop=True, timeout=5)
        return True
        
    except telebot.apihelper.ApiTelegramException as e:
        print(f"❌ Telegram API error: {e}")
        if "Unauthorized" in str(e):
            print("   The provided token is invalid. Please check with @BotFather.")
        return False
    except Exception as e:
        print(f"❌ Error testing bot: {e}")
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    print("\n🤖 Telegram Bot Test")
    print("===================")
    
    try:
        import clean_locks
        clean_locks.cleanup()
        
        success = test_bot_startup()
        print(f"\nTest completed: {'✅ Success' if success else '❌ Failed'}")
        
        if not success:
            print("\nTroubleshooting tips:")
            print("1. Check that your TELEGRAM_BOT_TOKEN is correct")
            print("2. Ensure you have internet connectivity")
            print("3. Try running debug_telegram.py for more detailed diagnostics")
            sys.exit(1)
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n✅ Polling test stopped by user. Bot appears to be working correctly.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print(traceback.format_exc())
        sys.exit(1)

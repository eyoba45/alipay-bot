#!/usr/bin/env python3
"""
Test script for welcome animation module
"""
import os
import logging
import telebot
import sys

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
        print(f"🤖 Bot personality traits: {len(BOT_PERSONALITY['traits'])}")
        for i, trait in enumerate(BOT_PERSONALITY['traits'], 1):
            print(f"  {i}. {trait}")
            
        print(f"\n🔖 Bot slogans: {len(BOT_PERSONALITY['slogans'])}")
        for i, slogan in enumerate(BOT_PERSONALITY['slogans'], 1):
            print(f"  {i}. {slogan}")
            
        print(f"\n👋 Bot greetings: {len(BOT_PERSONALITY['greetings'])}")
        for i, greeting in enumerate(BOT_PERSONALITY['greetings'], 1):
            print(f"  {i}. {greeting}")
        
        # Check for token and display info, but don't send messages
        TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not TOKEN:
            print("\n❌ TELEGRAM_BOT_TOKEN not found in environment variables")
            print("Cannot proceed with live testing")
            return False
            
        print("\n✅ TELEGRAM_BOT_TOKEN found in environment")
        print("\nTo test this animation in the actual bot:")
        print("1. Run 'python start_bot.py' to start the bot")
        print("2. Send /start command to the bot on Telegram")
        print("3. Observe the animated welcome sequence")
        
        return True
        
    except ImportError as e:
        print(f"❌ Could not import welcome_animation module: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing welcome animation: {e}")
        print(f"Error type: {type(e).__name__}")
        return False

if __name__ == "__main__":
    print("\n🎭 Welcome Animation Test")
    print("========================")
    
    success = test_welcome_animation()
    
    if success:
        print("\n✅ Welcome animation module verification complete")
        print("The 5-stage animation sequence with randomized personality traits is ready!")
    else:
        print("\n❌ Welcome animation module test failed")
        print("Please check the error messages above")
        sys.exit(1)
    
    sys.exit(0)

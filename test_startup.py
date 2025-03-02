"""Test bot startup sequence with detailed logging"""
import os
import logging
import sys
from datetime import datetime

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def test_environment():
    """Test environment variables"""
    required_vars = ['TELEGRAM_BOT_TOKEN', 'DATABASE_URL', 'ADMIN_CHAT_ID']
    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        logger.error(f"❌ Missing environment variables: {', '.join(missing)}")
        return False
    logger.info("✅ All required environment variables present")
    return True

def test_database():
    """Test database connection"""
    try:
        from database import init_db, get_session
        init_db()
        session = get_session()
        logger.info("✅ Database connection successful")
        session.close()
        return True
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        return False

def test_telegram():
    """Test Telegram connection"""
    try:
        import telebot
        bot = telebot.TeleBot(os.environ['TELEGRAM_BOT_TOKEN'])
        bot_info = bot.get_me()
        logger.info(f"✅ Connected to Telegram as @{bot_info.username}")
        
        # Test webhook status
        webhook_info = bot.get_webhook_info()
        logger.info(f"📊 Current webhook status: {webhook_info}")
        
        return True
    except Exception as e:
        logger.error(f"❌ Telegram connection failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("🔍 Starting diagnostic tests...")
    
    env_ok = test_environment()
    if not env_ok:
        sys.exit(1)
        
    db_ok = test_database()
    if not db_ok:
        sys.exit(1)
        
    telegram_ok = test_telegram()
    if not telegram_ok:
        sys.exit(1)
        
    logger.info("✅ All tests passed successfully")

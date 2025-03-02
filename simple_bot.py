
#!/usr/bin/env python3
"""
Simple Telegram Bot Runner - A clean and minimal bot runner that just works
"""
import os
import logging
import telebot
import time
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SimpleBotRunner")

# Get Telegram token
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("No TELEGRAM_BOT_TOKEN found in environment!")
    sys.exit(1)

# Initialize bot
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(
        message, 
        "👋 Welcome to AliPay_ETH!\n\nI'm here to help you shop on AliExpress using Ethiopian Birr."
    )
    logger.info(f"Sent welcome message to user {message.chat.id}")

@bot.message_handler(commands=['help'])
def help_command(message):
    bot.reply_to(
        message,
        "Need help? Here are the available commands:\n"
        "/start - Start the bot\n"
        "/help - Show this help message"
    )
    logger.info(f"Sent help message to user {message.chat.id}")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(
        message,
        "I received your message! The bot is working.\n"
        "Please use /start to begin."
    )
    logger.info(f"Sent reply to user {message.chat.id}")

def main():
    logger.info("🚀 Starting bot in polling mode...")
    
    # Delete any existing webhook
    try:
        bot.delete_webhook()
        logger.info("✅ Webhook cleared")
    except Exception as e:
        logger.error(f"Error clearing webhook: {e}")
    
    # Start polling
    while True:
        try:
            logger.info("Starting polling...")
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            logger.info("Restarting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    main()

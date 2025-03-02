
#!/usr/bin/env python3
"""
Robust Telegram Bot Runner with full functionality
"""
import os
import logging
import telebot
import time
import sys
import signal
import traceback
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Set up signal handling for graceful shutdown
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    logger.info("Shutdown signal received, exiting gracefully...")
    shutdown_requested = True

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Get Telegram token
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("❌ No TELEGRAM_BOT_TOKEN found in environment!")
    sys.exit(1)

# Initialize bot
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

def create_main_keyboard():
    """Create the main keyboard with buttons"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    button1 = KeyboardButton('💰 Shop Now')
    button2 = KeyboardButton('📦 My Orders')
    button3 = KeyboardButton('❓ Help')
    button4 = KeyboardButton('👤 My Account')
    
    markup.add(button1, button2)
    markup.add(button3, button4)
    
    return markup

def create_inline_keyboard():
    """Create inline keyboard for the welcome message"""
    markup = InlineKeyboardMarkup(row_width=2)
    
    button1 = InlineKeyboardButton("🛍️ Start Shopping", callback_data="start_shopping")
    button2 = InlineKeyboardButton("ℹ️ About Us", callback_data="about_us")
    button3 = InlineKeyboardButton("📞 Contact Support", callback_data="contact")
    
    markup.add(button1)
    markup.add(button2, button3)
    
    return markup

# This handler has been disabled to prevent duplicate welcome messages
# @bot.message_handler(commands=['start'])
def send_welcome(message):
    """Handle /start command with rich welcome message and buttons"""
    try:
        logger.info(f"Received /start from user {message.chat.id}")
        
        # Send welcome message with inline buttons
        bot.send_message(
            message.chat.id,
            "👋 <b>Welcome to AliPay_ETH!</b>\n\n"
            "I'm here to help you shop on AliExpress using Ethiopian Birr.\n\n"
            "• Browse products directly through our bot\n"
            "• Pay in Ethiopian Birr (ETB)\n"
            "• Track your orders easily\n"
            "• Get support when you need it\n\n"
            "What would you like to do today?",
            reply_markup=create_inline_keyboard()
        )
        
        # After a short delay, send keyboard
        time.sleep(0.5)
        bot.send_message(
            message.chat.id,
            "Please select an option from the menu below:",
            reply_markup=create_main_keyboard()
        )
        
        logger.info(f"Sent welcome message to user {message.chat.id}")
    except Exception as e:
        logger.error(f"❌ Error in start command: {traceback.format_exc()}")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """Handle inline keyboard button presses"""
    try:
        if call.data == "start_shopping":
            bot.answer_callback_query(call.id, "Let's start shopping!")
            bot.send_message(call.message.chat.id, "🛍️ <b>Shop AliExpress with ETB</b>\n\nWhat would you like to shop for today?")
        
        elif call.data == "about_us":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id, 
                "ℹ️ <b>About AliPay_ETH</b>\n\n"
                "We are a service that allows Ethiopian customers to shop on AliExpress using local currency (ETB).\n\n"
                "Our service handles all the international payment processing and delivery logistics for you!"
            )
        
        elif call.data == "contact":
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id, 
                "📞 <b>Contact Support</b>\n\n"
                "If you need any assistance, you can reach our support team at:\n"
                "• Email: support@alipay-eth.com\n"
                "• Telegram: @AliPay_ETH_Support\n\n"
                "Our support hours are Monday-Saturday, 9AM-6PM EAT."
            )
    except Exception as e:
        logger.error(f"❌ Error in callback handler: {traceback.format_exc()}")

@bot.message_handler(commands=['help'])
def help_command(message):
    """Handle /help command"""
    try:
        logger.info(f"Received /help from user {message.chat.id}")
        bot.reply_to(
            message,
            "Need help? Here are the available commands:\n\n"
            "/start - Start the bot and see main menu\n"
            "/help - Show this help message\n"
            "/shop - Browse products\n"
            "/orders - View your orders\n"
            "/account - Manage your account\n"
            "/support - Contact customer support",
            reply_markup=create_main_keyboard()
        )
        logger.info(f"Sent help message to user {message.chat.id}")
    except Exception as e:
        logger.error(f"❌ Error in help command: {traceback.format_exc()}")

@bot.message_handler(func=lambda message: message.text == '💰 Shop Now')
def shop_command(message):
    """Handle Shop Now button press"""
    try:
        bot.reply_to(
            message,
            "🛍️ <b>Shop AliExpress with ETB</b>\n\n"
            "You can shop by category or search for specific items.\n\n"
            "What would you like to shop for today?"
        )
    except Exception as e:
        logger.error(f"❌ Error in shop command: {traceback.format_exc()}")

@bot.message_handler(func=lambda message: message.text == '📦 My Orders')
def orders_command(message):
    """Handle My Orders button press"""
    try:
        bot.reply_to(
            message,
            "📦 <b>My Orders</b>\n\n"
            "You don't have any orders yet.\n\n"
            "Start shopping to see your orders here!"
        )
    except Exception as e:
        logger.error(f"❌ Error in orders command: {traceback.format_exc()}")

@bot.message_handler(func=lambda message: message.text == '❓ Help')
def help_button(message):
    """Handle Help button press"""
    try:
        help_command(message)
    except Exception as e:
        logger.error(f"❌ Error in help button: {traceback.format_exc()}")

@bot.message_handler(func=lambda message: message.text == '👤 My Account')
def account_command(message):
    """Handle My Account button press"""
    try:
        bot.reply_to(
            message,
            "👤 <b>My Account</b>\n\n"
            "Your account information:\n"
            "• Username: " + (message.from_user.username or "Not set") + "\n"
            "• User ID: " + str(message.from_user.id) + "\n\n"
            "You can manage your delivery addresses and payment methods here."
        )
    except Exception as e:
        logger.error(f"❌ Error in account command: {traceback.format_exc()}")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    """Handle all other messages"""
    try:
        logger.info(f"Received message from user {message.chat.id}: {message.text}")
        bot.reply_to(
            message,
            "I received your message! If you need help, please use the menu buttons below or type /help.",
            reply_markup=create_main_keyboard()
        )
        logger.info(f"Sent reply to user {message.chat.id}")
    except Exception as e:
        logger.error(f"❌ Error in message handler: {traceback.format_exc()}")

def main():
    logger.info("🚀 Starting bot in polling mode...")
    
    # Delete any existing webhook
    try:
        bot.delete_webhook()
        logger.info("✅ Webhook cleared")
    except Exception as e:
        logger.error(f"Error clearing webhook: {e}")
    
    # Start polling with recovery
    while not shutdown_requested:
        try:
            logger.info("Starting polling...")
            bot.polling(none_stop=True, timeout=60, interval=1)
        except Exception as e:
            if shutdown_requested:
                break
            logger.error(f"Polling error: {e}")
            logger.info("Restarting in 5 seconds...")
            time.sleep(5)
    
    logger.info("Bot shutdown complete")

if __name__ == "__main__":
    main()

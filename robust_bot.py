
#!/usr/bin/env python3
"""
Robust bot runner with watchdog and automatic recovery
"""
import os
import sys
import time
import logging
import subprocess
import signal
import threading
import traceback
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_monitor.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Shutdown flag
shutdown_requested = False

def run_keep_alive():
    """Run the keep-alive server in a separate process"""
    try:
        logger.info("🌐 Starting keep-alive server...")
        subprocess.Popen([sys.executable, "keep_alive.py"], 
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT)
        logger.info("✅ Keep-alive server started")
        
        # Verify keep-alive is working
        time.sleep(3)  # Give it time to start
        for attempt in range(5):
            try:
                response = requests.get('http://127.0.0.1:5000/ping', timeout=5)
                if response.status_code == 200 and response.text == "pong":
                    logger.info("✅ Keep-alive verified")
                    return True
                logger.warning(f"Keep-alive responded with {response.status_code}: {response.text}")
            except requests.ConnectionError:
                logger.warning(f"Keep-alive not ready (attempt {attempt+1}/5)")
                time.sleep(1)
        
        logger.error("❌ Keep-alive verification failed")
        return False
    except Exception as e:
        logger.error(f"❌ Error starting keep-alive: {e}")
        logger.error(traceback.format_exc())
        return False

def run_bot():
    """Run the main bot process and monitor it"""
    try:
        logger.info("🤖 Starting bot...")
        # Clean up environment first
        subprocess.run([sys.executable, "clean_locks.py"], check=True)
        
        # Start the bot
        bot_process = subprocess.Popen(
            [sys.executable, "bot.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        logger.info(f"✅ Bot started with PID {bot_process.pid}")
        
        # Monitor the bot process
        while bot_process.poll() is None and not shutdown_requested:
            line = bot_process.stdout.readline()
            if line:
                logger.info(f"[BOT] {line.strip()}")
            
            # Check if there are error patterns that require immediate restart
            if "TeleBot: Threaded polling exception" in line or "ConnectionError" in line:
                logger.warning("⚠️ Bot encountered a connection error. Planning restart...")
                # Give it a moment to recover on its own
                time.sleep(5)
                
                # If it's still running but has connection issues, kill it for restart
                if bot_process.poll() is None:
                    logger.warning("🔄 Killing bot process for restart...")
                    bot_process.terminate()
                    time.sleep(2)
                    if bot_process.poll() is None:
                        bot_process.kill()
                break
        
        exit_code = bot_process.returncode
        logger.info(f"Bot exited with code {exit_code}")
        return exit_code
    except Exception as e:
        logger.error(f"❌ Error running bot: {e}")
        logger.error(traceback.format_exc())
        return 1

def check_internet_connectivity():
    """Check if we have internet connectivity"""
    try:
        requests.get("https://api.telegram.org", timeout=5)
        return True
    except:
        return False

def signal_handler(sig, frame):
    """Handle termination signals gracefully"""
    global shutdown_requested
    logger.info(f"Received signal {sig}, shutting down...")
    shutdown_requested = True

def main():
    """Main entry point with restart logic"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start keep-alive server
    if not run_keep_alive():
        logger.error("❌ Failed to start keep-alive. Exiting.")
        return 1
    
    # Run bot with automatic restarts
    consecutive_failures = 0
    while not shutdown_requested:
        # Check internet before starting
        if not check_internet_connectivity():
            logger.error("❌ No internet connectivity. Waiting before retry...")
            time.sleep(30)
            continue
        
        exit_code = run_bot()
        
        if exit_code != 0:
            consecutive_failures += 1
            logger.warning(f"⚠️ Bot exited with code {exit_code}. Consecutive failures: {consecutive_failures}")
            
            # Implement exponential backoff for repeated failures
            if consecutive_failures > 5:
                sleep_time = min(300, 30 * (consecutive_failures - 5))  # Max 5 minutes
                logger.warning(f"⏱️ Waiting {sleep_time}s before next restart attempt")
                
                # Check if shutdown was requested during sleep
                for _ in range(sleep_time):
                    if shutdown_requested:
                        break
                    time.sleep(1)
            else:
                time.sleep(5)  # Short delay for first few failures
        else:
            # Reset failure counter on clean exit
            consecutive_failures = 0
            
            # If shutdown requested or clean exit, don't restart
            if shutdown_requested:
                break
            else:
                logger.info("Bot exited cleanly. Restarting in 5 seconds...")
                time.sleep(5)
    
    logger.info("👋 Shutting down bot runner")
    return 0

if __name__ == "__main__":
    sys.exit(main())


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

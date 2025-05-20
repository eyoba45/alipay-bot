#!/usr/bin/env python3
"""
Telegram Bot Runner with enhanced functionality
Implements unlimited request handling system to prevent crashes under heavy load
with smart error recovery for bot interruptions
"""
import os
import logging
import sys
import telebot
import time
import traceback
import signal
import threading
import fcntl
import requests
import queue
import urllib.parse
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from connection_manager import init_db, get_session, safe_close_session, session_scope
from models import User, Order, PendingApproval, PendingDeposit, CompanionProfile, CompanionInteraction, Transaction
from datetime import datetime, timedelta
from sqlalchemy import func
# Import our new modules for unlimited request handling
from request_manager import request_manager, managed_request
from error_handler import error_handler, safe_handler
# Import bot recovery system
from bot_recovery import recovery_manager, with_state_recovery, clear_state

# Dictionary to track users in active companion conversations
# Key: chat_id, Value: Boolean (True if in companion conversation)
companion_conversations = {}

# Import the AI Assistant
try:
    from digital_companion import DigitalCompanion
    COMPANION_ENABLED = True
    logger = logging.getLogger('bot')
    logger.info("Digital Companion module loaded successfully")
except ImportError as e:
    COMPANION_ENABLED = False
    logger = logging.getLogger('bot')
    logger.warning(f"Digital Companion not available: {e}")
    logger.warning("Bot will run without digital companion features")
    logger.warning(f"AI Assistant not available: {e}")
    COMPANION_ENABLED = False

# Decorator to check subscription status
def subscription_required(func):
    """Decorator to ensure user has a valid subscription before accessing features"""
    def wrapper(message, *args, **kwargs):
        chat_id = message.chat.id

        # Allow deposit feature to work even with expired subscription
        func_name = func.__name__
        if func_name in ['deposit_funds', 'deposit_funds_internal', 'handle_deposit_amount', 
                         'send_payment_details', 'payment_details', 'process_custom_amount',
                         'handle_deposit_screenshot']:
            # Always allow deposit related functions
            return func(message, *args, **kwargs)

        # Check if user has a valid subscription
        if not has_valid_subscription(chat_id):
            # User doesn't have a valid subscription, send locked message
            # This will be handled inside has_valid_subscription for renewal instructions

            bot.send_message(
                chat_id,
                """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔒 <b>FEATURE LOCKED</b> 🔒  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

This feature requires an active subscription.

Your subscription has expired. Please deposit funds to your account 
to automatically renew your subscription ($1.00 will be deducted).

Use the 💰 Deposit button to add funds to your account.
""",
                parse_mode='HTML'
            )
            logger.info(f"Blocked access to feature for user {chat_id} due to expired subscription")
            return

        # User has valid subscription, proceed with original function
        return func(message, *args, **kwargs)

    return wrapper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Set up signal handling for graceful shutdown
shutdown_requested = False
bot_instance = None

def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown"""
    global shutdown_requested, bot_instance
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_requested = True
    if bot_instance:
        try:
            logger.info("Stopping bot polling...")
            bot_instance.stop_polling()
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# Get Telegram token
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_ID_STR = os.environ.get('ADMIN_CHAT_ID', '')

if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN not found!")
    sys.exit(1)

# Support for multiple admin IDs, comma-separated
ADMIN_IDS = []
try:
    # Parse comma-separated admin IDs
    for admin_id in ADMIN_ID_STR.split(','):
        admin_id = admin_id.strip()
        if admin_id:
            ADMIN_IDS.append(int(admin_id))

    # Keep ADMIN_ID for backward compatibility
    ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else None

    if ADMIN_IDS:
        logger.info(f"✅ Configured {len(ADMIN_IDS)} admin IDs")
    else:
        logger.warning("⚠️ No valid admin IDs found. Admin features will be disabled.")
except (ValueError, TypeError, IndexError):
    logger.warning("⚠️ ADMIN_CHAT_ID is not valid. Admin notifications will be skipped.")
    ADMIN_ID = None
    ADMIN_IDS = []

# Initialize bot with large timeout
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
bot_instance = bot  # Store reference for signal handling

_user_cache = {}
user_states = {}
registration_data = {}
digital_companion = None  # Will be initialized in main() if COMPANION_ENABLED

# Dictionary to track users with expired subscriptions
# Key: user_id, Value: Boolean (True if subscription is expired)
expired_subscriptions = {}

def has_valid_subscription(user_id):
    """Check if a user has a valid subscription or should be blocked from using features

    This function also handles auto-renewal from user balance if possible
    """
    if is_admin(user_id):
        return True  # Admins always have access

    # Check if user is registered
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            return False  # Not registered

        # If no subscription date, user hasn't paid yet
        if not user.subscription_date:
            return False

        # Calculate if subscription is active
        days_passed = (datetime.utcnow() - user.subscription_date).days

        # If subscription is active, return True
        if days_passed < 30:
            # If they were in expired dict, remove them
            if user_id in expired_subscriptions:
                del expired_subscriptions[user_id]
            return True

        # Subscription has expired, try to auto-renew from balance
        if user.balance >= 1.0:  # User has enough balance to auto-renew ($1)
            # Deduct subscription fee
            previous_balance = user.balance
            user.balance -= 1.0

            # Update subscription date
            user.subscription_date = datetime.utcnow()
            session.commit()

            # Notify user about automatic renewal
            try:
                bot.send_message(
                    user_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>SUBSCRIPTION RENEWED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has been automatically renewed for 30 days.

💰 <b>Previous balance:</b> ${previous_balance:.2f}
💵 <b>Subscription fee:</b> $1.00
💼 <b>New balance:</b> ${user.balance:.2f}

Your subscription will expire on {(datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")}.
""",
                    parse_mode='HTML'
                )

                # Notify admin about the renewal
                for admin_id in ADMIN_IDS:
                    try:
                        bot.send_message(
                            admin_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💲 <b>SUBSCRIPTION AUTO-RENEWED</b>  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Subscription auto-renewed for user:
👤 <b>{user.name}</b> [ID: <code>{user_id}</code>]
💰 Previous balance: ${previous_balance:.2f}
💰 New balance: ${user.balance:.2f}
""",
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Error notifying admin {admin_id} about auto-renewal: {e}")

                logger.info(f"✅ Auto-renewed subscription for user {user_id} from balance")

                # Remove from expired dict if present
                if user_id in expired_subscriptions:
                    del expired_subscriptions[user_id]

                return True
            except Exception as e:
                logger.error(f"Error notifying about subscription renewal: {e}")
                return True  # Still return True since subscription was renewed

        # Subscription expired and not enough balance to auto-renew
        # Mark this user as expired if not already marked
        if user_id not in expired_subscriptions:
            expired_subscriptions[user_id] = True
            try:
                # Send subscription expired message instructing to deposit funds
                bot.send_message(
                    user_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔒 <b>SUBSCRIPTION LOCKED</b> 🔒  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has expired and your balance is too low for automatic renewal.

To continue using all bot features, please:

1. Use the 💰 <b>Deposit</b> button in the main menu to add funds to your account
2. When you have at least $1.00 balance, your subscription will be automatically renewed

Subscription fee: $1.00 (150 birr)

<i>Note: Deposit functionality is still available even with an expired subscription.</i>
""",
                    parse_mode='HTML'
                )

                logger.info(f"Sent subscription locked notification to user {user_id}")
            except Exception as e:
                logger.error(f"Error processing expired subscription for {user_id}: {e}")

        return False  # Subscription expired

    except Exception as e:
        logger.error(f"Error checking subscription status: {e}")
        return False  # Error checking subscription
    finally:
        safe_close_session(session)


def is_admin(chat_id):
    """Check if a user is an admin"""
    return chat_id in ADMIN_IDS

def create_main_menu(is_registered=False, chat_id=None):
    """Create the main menu keyboard based on registration status and admin status"""
    menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

    # Check if this is an admin user
    is_admin_user = chat_id is not None and is_admin(chat_id)

    if is_registered:
        menu.add(
            KeyboardButton('💰 Deposit'),
            KeyboardButton('📦 Submit Order')
        )
        menu.add(
            KeyboardButton('📊 Order Status'),
            KeyboardButton('🔍 Track Order')
        )
        menu.add(
            KeyboardButton('💳 Balance'),
            KeyboardButton('📅 Subscription')
        )
        menu.add(
            KeyboardButton('🏆 Referral Badges (Coming Soon)'),
            KeyboardButton('🔗 My Referral Link (Coming Soon)')
        )
        menu.add(
            KeyboardButton('👥 Join Community'),
            KeyboardButton('❓ Help Center')
        )

        # Add AI Assistant button if enabled
        if COMPANION_ENABLED:
            menu.add(KeyboardButton('🤖 AI Assistant'))

        # Add admin buttons for admin users
        if is_admin_user:
            menu.add(KeyboardButton('🔐 Admin Dashboard'))
    else:
        menu.add(KeyboardButton('🔑 Register'))
        menu.add(
            KeyboardButton('👥 Join Community'),
            KeyboardButton('❓ Help Center')
        )

        # Add AI Assistant button for unregistered users too
        if COMPANION_ENABLED:
            menu.add(KeyboardButton('🤖 AI Assistant'))

        # Add admin buttons for admin users, even if not registered
        if is_admin_user:
            menu.add(KeyboardButton('🔐 Admin Dashboard'))

    return menu

@bot.message_handler(commands=['admin'])
def admin_command(message):
    """Direct access to admin dashboard via command"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        bot.send_message(
            chat_id,
            "⚠️ You don't have permission to access the admin dashboard.",
            reply_markup=create_main_menu(False, chat_id)
        )
        return

    # If admin, redirect to admin dashboard
    admin_dashboard(message)

@bot.message_handler(commands=['start'])
def start_message(message):
    """Handle /start command with animated welcome"""
    chat_id = message.chat.id
    session = None
    try:
        logger.info(f"Received /start from user {chat_id}")

        # Check for referral code in the start command
        referral_code = None
        if message.text and len(message.text.split()) > 1:
            # Extract potential referral code
            referral_code = message.text.split()[1].strip()
            logger.info(f"Start command with potential referral code: {referral_code}")
            # Store in registration data for later use
            if chat_id not in registration_data:
                registration_data[chat_id] = {}
            registration_data[chat_id]['referral_code'] = referral_code

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        is_registered = user is not None

        # Reset user state if any
        if chat_id in user_states:
            del user_states[chat_id]

        # Keep referral code if present
        if referral_code and referral_code not in registration_data.get(chat_id, {}):
            if chat_id not in registration_data:
                registration_data[chat_id] = {}
            registration_data[chat_id]['referral_code'] = referral_code

        # Check if user is admin
        is_admin_user = is_admin(chat_id)

        # Get user's name if registered
        user_name = user.name if user else message.from_user.first_name if message.from_user else None

        # Import and use the enhanced welcome animation module
        try:
            from welcome_animation import send_personalized_welcome
            logger.info(f"✅ Successfully imported welcome animation module for user {chat_id}")
        except ImportError as e:
            logger.error(f"❌ Failed to import welcome animation module: {e}")
            logger.warning("Enhanced welcome animation module not found, using fallback welcome")

            # Define fallback welcome animation function
            def send_personalized_welcome(bot, chat_id, user_data=None):
                """Fallback welcome message if module not available"""
                name = "there"
                if user_data and 'name' in user_data and user_data['name']:
                    name = user_data['name']

                return bot.send_message(
                    chat_id,
                    f"<b>Hello {name}!</b>\n\n✨ Welcome to AliPay_ETH! ✨\n\nYour Ethiopian gateway to AliExpress shopping.",
                    parse_mode='HTML'
                )

        # Send animated welcome message with bot personality introduction
        logger.info(f"Attempting to send personalized welcome animation to user {chat_id}")
        try:
            # Check if welcome_animation.py has the proper function and content
            import os
            welcome_path = os.path.join(os.getcwd(), 'welcome_animation.py')
            if os.path.exists(welcome_path):
                logger.info(f"✅ welcome_animation.py file exists at {welcome_path}")
                with open(welcome_path, 'r') as f:
                    content_length = len(f.read())
                    logger.info(f"✅ welcome_animation.py file size: {content_length} bytes")
            else:
                logger.error(f"❌ welcome_animation.py file DOES NOT EXIST at {welcome_path}")

            # Call the welcome animation function with appropriate error handling
            welcome_message = send_personalized_welcome(bot, chat_id, {'name': user_name})
            logger.info(f"✅ Successfully sent welcome animation to user {chat_id}")
        except Exception as e:
            logger.error(f"❌ Error sending welcome animation: {str(e)}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            # Send fallback message directly if animation fails
            return bot.send_message(
                chat_id,
                f"<b>Hello {user_name or 'there'}!</b>\n\n✨ Welcome to AliPay_ETH! ✨\n\nYour Ethiopian gateway to AliExpress shopping.",
                parse_mode='HTML'
            )

        # Different welcome message for admins
        if is_admin_user:
            welcome_msg = """
✨ <b>Welcome to AliPay_ETH Admin Panel!</b> ✨

You are logged in as an administrator. You have access to all regular user functions plus admin features.

🔐 <b>ADMIN FEATURES:</b>
• User management
• Order management
• Deposit management
• System statistics
• Subscription management

Click '🔐 Admin Dashboard' to access admin features.
"""
        else:
            welcome_msg = """
✨ <b>Welcome to AliPay_ETH!</b> ✨

Your trusted Ethiopian payment solution for AliExpress shopping!

🛍️ <b>What We Offer:</b>
• Shop on AliExpress with Ethiopian Birr
• Fast order processing & tracking
• Reliable customer support
• Secure payment handling

💫 <b>Monthly Subscription:</b>
• Just $1 subscription per month
• Access to all features and support
• Automatic renewal monthly

🌟 Ready to start shopping? Click '<b>🔑 Register</b>' below to begin your journey! 🌟
"""
        # Slight delay to allow animation to complete
        time.sleep(1.5)

        # Send detailed welcome information
        bot.send_message(
            chat_id,
            welcome_msg,
            reply_markup=create_main_menu(is_registered, chat_id),
            parse_mode='HTML'
        )
        logger.info(f"Sent welcome message to user {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error in start command: {traceback.format_exc()}")
        bot.send_message(chat_id, "Welcome to AliPay_ETH!", reply_markup=create_main_menu(False, chat_id))
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '🔑 Register')
def register_user(message):
    """Start the registration process"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        # Check if user already exists
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        if user:
            bot.send_message(
                chat_id,
                """
✅ <b>You are already registered!</b>

Your account is active and ready to use.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )
            return

        # Only check pending approvals if user is not yet registered
        pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()
        if pending:
            # First verify if the payment was successful but user not created yet
            if pending.tx_ref:
                # Try to verify the payment one more time directly
                try:
                    from chapa_payment import verify_payment
                    payment_status = verify_payment(pending.tx_ref)

                    # If payment is successful, create user immediately
                    if payment_status and payment_status.get('status') == 'success':
                        from chapa_autopay import process_verified_registration
                        if process_verified_registration(chat_id, payment_status):
                            # User was created - redirect to main menu
                            bot.send_message(
                                chat_id,
                                """
✅ <b>Registration Successful!</b>

Your account is now active and ready to use.
""",
                                parse_mode='HTML',
                                reply_markup=create_main_menu(is_registered=True)
                            )
                            return
                except Exception as e:
                    logger.error(f"Error checking payment status: {e}")
                    # Continue with standard flow if verification fails

                # If verification failed or payment not yet successful, redirect to make payment
                bot.send_message(
                    chat_id,
                    """
🔸 <b>Complete Your Registration</b>

Please complete your payment to activate your account.
""",
                    parse_mode='HTML',
                    reply_markup=create_main_menu(is_registered=False)
                )
            else:
                bot.send_message(
                    chat_id,
                    """
🔸 <b>Complete Your Registration</b>

Please complete your registration by making the payment.
""",
                    parse_mode='HTML',
                    reply_markup=create_main_menu(is_registered=False)
                )
            return

        # Initialize registration state
        user_states[chat_id] = 'waiting_for_name'
        registration_data[chat_id] = {}

        # Ask for full name
        bot.send_message(chat_id, "Please enter your full name:")
    except Exception as e:
        logger.error(f"Error in registration: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_name')
def get_name(message):
    """Process the name and ask for address"""
    chat_id = message.chat.id
    registration_data[chat_id]['name'] = message.text
    user_states[chat_id] = 'waiting_for_address'
    bot.send_message(chat_id, "Please enter your address:")

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_address')
def get_address(message):
    """Process the address and ask for phone"""
    chat_id = message.chat.id
    registration_data[chat_id]['address'] = message.text
    user_states[chat_id] = 'waiting_for_phone'
    bot.send_message(chat_id, "Please enter your phone number:")

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_phone')
def get_phone(message):
    """Process phone and request payment using Chapa"""
    chat_id = message.chat.id
    session = None
    try:
        phone = message.text.strip().replace(" ", "")

        # Validate Ethiopian phone number
        is_valid = False
        if phone.startswith('+2519') and len(phone) == 13 and phone[1:].isdigit():
            is_valid = True
        elif phone.startswith('09') and len(phone) == 10 and phone.isdigit():
            is_valid = True

        if not is_valid:
            bot.send_message(chat_id, "❌ Invalid phone number! Please enter a valid Ethiopian number (e.g., 0912345678 or +251912345678)")
            return

        registration_data[chat_id]['phone'] = phone
        registration_data[chat_id]['telegram_id'] = chat_id
        user_states[chat_id] = 'waiting_for_payment'

        # Move imports here to avoid circular imports
        from chapa_payment import generate_registration_payment

        # Create a pending approval
        session = get_session()
        existing_pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()

        if not existing_pending:
            pending = PendingApproval(
                telegram_id=chat_id,
                name=registration_data[chat_id]['name'],
                phone=registration_data[chat_id]['phone'],
                address=registration_data[chat_id]['address']
            )
            session.add(pending)
            session.commit()
            logger.info(f"Added pending approval for user {chat_id}")

        # Import the Chapa payment module
        from chapa_payment import generate_registration_payment

        # Generate payment link
        payment_link = generate_registration_payment(registration_data[chat_id])

        if not payment_link or 'checkout_url' not in payment_link:
            # Fall back to manual payment if Chapa integration fails
            payment_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🌟 <b>REGISTRATION DETAILS</b> 🌟  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>👤 YOUR INFORMATION:</b>
• Name: <b>{registration_data[chat_id]['name']}</b>
• Phone: <code>{registration_data[chat_id]['phone']}</code>
• Address: <i>{registration_data[chat_id]['address']}</i>

<b>💎 REGISTRATION FEE:</b>
• ETB: <code>150</code> birr

<b>💳 SELECT PAYMENT METHOD:</b>

<b>🏦 Commercial Bank (CBE)</b>
• Account: <code>1000547241316</code>
• Name: <code>Eyob Mulugeta</code>

<b>📱 TeleBirr Mobile Money</b>
• Number: <code>0986693062</code>
• Name: <code>Eyob Mulugeta</code>

<b>📱 HOW TO COMPLETE:</b>
1️⃣ Select your preferred payment option
2️⃣ Transfer exactly <code>150 ETB</code>
3️⃣ Capture a clear screenshot of confirmation
4️⃣ Send the screenshot below ⬇️

<i>Join thousands of satisfied members shopping on AliExpress with ETB!</i>
"""
            bot.send_message(chat_id, payment_msg, parse_mode='HTML')
        else:
            # Send Chapa payment link with inline button
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("💳 Pay Now", url=payment_link['checkout_url']))

            payment_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🌟 <b>REGISTRATION DETAILS</b> 🌟  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>👤 YOUR INFORMATION:</b>
• Name: <b>{registration_data[chat_id]['name']}</b>
• Phone: <code>{registration_data[chat_id]['phone']}</code>
• Address: <i>{registration_data[chat_id]['address']}</i>

<b>💎 REGISTRATION FEE:</b>
• One-time fee: <code>200</code> birr
• First month subscription: <code>150</code> birr
• Total payment: <code>350</code> birr
• Secure payment via Chapa
• Instant activation after payment

<b>✨ EASY PAYMENT OPTIONS ✨</b>

Click the button below to pay securely with:
• Credit/Debit Card
• TeleBirr
• CBE Birr
• HelloCash
• And more payment options!

<i>Your account will be automatically activated after payment!</i>
"""
            bot.send_message(chat_id, payment_msg, parse_mode='HTML', reply_markup=markup)

            # Store transaction reference for later verification
            user_states[chat_id] = {
                'state': 'waiting_for_chapa_payment',
                'tx_ref': payment_link['tx_ref']
            }

    except Exception as e:
        logger.error(f"Error processing phone: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_payment')
def handle_payment_registration(message):
    """Process registration payment with Chapa integration and enhanced security"""
    chat_id = message.chat.id
    session = None

    try:
        if chat_id not in registration_data:
            logger.error(f"Missing registration data for user {chat_id}")
            bot.send_message(chat_id, "Registration data missing. Please restart registration with /start.")
            return

        # Check if user is already registered
        session = get_session()
        existing_user = session.query(User).filter_by(telegram_id=chat_id).first()
        if existing_user:
            logger.warning(f"User {chat_id} attempted re-registration but is already registered")
            bot.send_message(
                chat_id,
                "✅ You're already registered! No need to register again.",
                reply_markup=create_main_menu(is_registered=True, chat_id=chat_id)
            )
            return

        # Verify Chapa API key is available before attempting payment
        if not os.environ.get('CHAPA_SECRET_KEY'):
            logger.error("CHAPA_SECRET_KEY not found in environment - payment system unavailable")
            bot.send_message(
                chat_id,
                "❌ Our payment system is currently unavailable. Please try again later or contact support.",
                parse_mode='HTML'
            )
            return

        # Import the Chapa payment module
        from chapa_payment import generate_registration_payment

        # Store registration information securely in database
        try:
            # First check if there's an existing pending registration
            pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()

            # Create or update pending approval record with registration data
            if pending:
                logger.info(f"Updating existing pending registration for user {chat_id}")
                pending.name = registration_data[chat_id]['name']
                pending.phone = registration_data[chat_id]['phone']
                pending.address = registration_data[chat_id]['address']
                pending.status = 'Pending Payment'
                pending.created_at = datetime.utcnow()
            else:
                logger.info(f"Creating new pending registration for user {chat_id}")
                pending = PendingApproval(
                    telegram_id=chat_id,
                    name=registration_data[chat_id]['name'],
                    phone=registration_data[chat_id]['phone'],
                    address=registration_data[chat_id]['address'],
                    status='Pending Payment',
                    created_at=datetime.utcnow()
                )
                session.add(pending)

            session.commit()
            logger.info(f"Successfully stored registration data for user {chat_id}")
        except Exception as e:
            logger.error(f"Error storing registration data: {e}")
            session.rollback()
            # Continue anyway to avoid blocking registration process

        # Generate payment link with proper security
        user_data = registration_data[chat_id].copy()
        user_data['telegram_id'] = chat_id  # Ensure telegram_id is included
        payment_link = generate_registration_payment(user_data)

        if not payment_link or 'checkout_url' not in payment_link:
            # Fall back to error message
            bot.send_message(
                chat_id,
                "❌ Error generating payment link. Please try again or contact support.",
                parse_mode='HTML'
            )
            return

        # Save the tx_ref to pending approval record for later verification
        try:
            pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()
            if pending:
                pending.tx_ref = payment_link['tx_ref']
                pending.payment_status = 'Pending'
                session.commit()
                logger.info(f"Updated pending registration with tx_ref: {payment_link['tx_ref']} for user {chat_id}")
        except Exception as e:
            logger.error(f"Error updating pending approval tx_ref: {e}")
            session.rollback()
            # Continue anyway

        # Send payment link with inline button
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💳 Pay Registration Fee", url=payment_link['checkout_url']))

        payment_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💫 <b>COMPLETE REGISTRATION</b> 💫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Click the button below to securely pay the registration fee:
• One-time fee: <code>200</code> birr
• First month subscription: <code>150</code> birr
• Total payment: <code>350</code> birr
• Secure payment via Chapa
• Instant activation after payment

<b>Available Payment Methods:</b>
• TeleBirr
• CBE Birr
• HelloCash
• Amole
• Credit/Debit Cards

<i>Your account will be automatically activated after successful payment verification!</i>

<b>Transaction Reference:</b> <code>{payment_link['tx_ref']}</code>
"""
        bot.send_message(
            chat_id,
            payment_msg,
            parse_mode='HTML',
            reply_markup=markup
        )

        # Update user state to wait for Chapa payment
        user_states[chat_id] = {
            'state': 'waiting_for_chapa_payment',
            'tx_ref': payment_link['tx_ref']
        }

        # Send follow-up information message
        time.sleep(1)
        bot.send_message(
            chat_id,
            """
<b>⚠️ IMPORTANT PAYMENT INFORMATION:</b>

After completing your payment:
• Wait for automatic verification (1-2 minutes)
• Do NOT close the payment page until you see "Payment Successful"
• Your account will be activated once payment is verified

If you don't receive confirmation within 5 minutes, please contact support.
""",
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error in payment registration: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "Sorry, there was an error. Please try again.",
            reply_markup=create_main_menu(is_registered=False)
        )
    finally:
        safe_close_session(session)

    # Import performance monitor if available
    try:
        from monitor_performance import monitor
        has_monitor = True
    except ImportError:
        has_monitor = False

    # Set a timeout for the entire operation
    registration_timeout = threading.Timer(
        30.0, 
        lambda: bot.send_message(
            chat_id, 
            "⏱️ Registration is taking longer than expected. We're still processing your request."
        )
    )
    registration_timeout.start()

    try:
        # Get the highest quality photo
        file_id = message.photo[-1].file_id
        logger.info(f"Received payment screenshot from user {chat_id}")

        # First send immediate acknowledgement to user
        immediate_ack = bot.send_message(
            chat_id,
            "📸 Screenshot received! Processing your registration...",
            parse_mode='HTML'
        )

        # Check if user already exists
        existing_user = None
        for db_attempt in range(3):  # Retry DB operations
            try:
                session = get_session()
                existing_user = session.query(User).filter_by(telegram_id=chat_id).first()

                if existing_user:
                    logger.info(f"User {chat_id} is already registered")
                    bot.send_message(
                        chat_id,
                        f"""
✅ <b>You are already registered!</b>

Your account is active and ready to use.
""",
                        parse_mode='HTML',
                        reply_markup=create_main_menu(is_registered=True)
                    )
                    safe_close_session(session)
                    return

                # Check for existing pending approval
                existing_pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()
                if existing_pending:
                    logger.info(f"User {chat_id} already has a pending approval - asking to complete payment")
                    break
                break
            except Exception as db_error:
                logger.error(f"Database check error (attempt {db_attempt+1}): {db_error}")
                safe_close_session(session)
                if db_attempt == 2:  # Last attempt failed
                    raise
                time.sleep(0.5 * (db_attempt + 1))  # Progressive delay

        # SECURE PAYMENT VERIFICATION: Always verify payment before approving
        max_retries = 5
        registration_complete = False  # Track completion status

        for retry_count in range(max_retries):
            try:
                # Always get a fresh session for each retry
                if session:
                    safe_close_session(session)
                session = get_session()

                # First, check if there's an existing pending approval
                existing_pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()

                if not existing_pending:
                    # Create or update pending approval
                    new_pending = PendingApproval(
                        telegram_id=chat_id,
                        name=registration_data[chat_id].get('name', ''),
                        phone=registration_data[chat_id].get('phone', ''),
                        address=registration_data[chat_id].get('address', ''),
                        status='Manual Verification',
                        created_at=datetime.utcnow()
                    )
                    session.add(new_pending)
                    session.commit()
                    logger.info(f"Created pending approval for user {chat_id}")

                    # Send manual verification notice to admin
                    if ADMIN_ID:
                        admin_msg = f"""
⏳ <b>REGISTRATION NEEDS VERIFICATION</b>

User Information:
Name: <b>{registration_data[chat_id].get('name', '')}</b>
Address: {registration_data[chat_id].get('address', '')}
Phone: <code>{registration_data[chat_id].get('phone', '')}</code>
ID: <code>{chat_id}</code>

Registration Fee: 350 ETB (200 ETB one-time + 150 ETB first month)
Payment screenshot attached below
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

⚠️ Automatic payment verification is enabled, but user submitted screenshot.
This payment requires MANUAL VERIFICATION in the Admin Dashboard.
"""
                        try:
                            admin_sent = bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')
                            bot.send_photo(ADMIN_ID, file_id, caption="📸 Registration Payment Screenshot")

                            # Send inline buttons for admin to approve/reject
                            approve_markup = InlineKeyboardMarkup()
                            approve_markup.row(
                                InlineKeyboardButton("✅ Approve", callback_data=f"approve_user_{chat_id}"),
                                InlineKeyboardButton("❌ Reject", callback_data=f"reject_user_{chat_id}")
                            )

                            bot.send_message(
                                ADMIN_ID,
                                f"Admin action needed for user {chat_id}:",
                                reply_markup=approve_markup
                            )
                        except Exception as admin_error:
                            logger.error(f"Error notifying admin about registration: {admin_error}")
                else:
                    # Update existing pending approval with screenshot information
                    existing_pending.status = 'Manual Verification'
                    existing_pending.updated_at = datetime.utcnow()
                    session.commit()
                    logger.info(f"Updated pending approval for user {chat_id}")

                    # Send admin notification
                    if ADMIN_ID:
                        admin_msg = f"""
⏳ <b>REGISTRATION UPDATE (PENDING)</b>

User Information:
Name: <b>{existing_pending.name}</b>
Address: {existing_pending.address}
Phone: <code>{existing_pending.phone}</code>
ID: <code>{chat_id}</code>

The user has submitted a payment screenshot.
Transaction Reference: <code>{existing_pending.tx_ref or 'None'}</code>
Status: Manual Verification Needed

⚠️ Please verify if the payment has been completed.
"""
                        try:
                            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')
                            bot.send_photo(ADMIN_ID, file_id, caption="📸 Registration Payment Screenshot (Update)")

                            # Send inline buttons for admin to approve/reject
                            approve_markup = InlineKeyboardMarkup()
                            approve_markup.row(
                                InlineKeyboardButton("✅ Approve", callback_data=f"approve_user_{chat_id}"),
                                InlineKeyboardButton("❌ Reject", callback_data=f"reject_user_{chat_id}")
                            )

                            bot.send_message(
                                ADMIN_ID,
                                f"Admin action needed for user {chat_id}:",
                                reply_markup=approve_markup
                            )
                        except Exception as admin_error:
                            logger.error(f"Error notifying admin about registration update: {admin_error}")

                # Tell the user that their registration is pending verification
                bot.send_message(
                    chat_id,
                    """
⏳ <b>REGISTRATION BEING VERIFIED</b>

Thank you for submitting your payment information!

Your registration is now pending verification. This typically takes 5-15 minutes.
You'll receive a notification once your account is activated.

For faster verification:
• Make sure you've completed the payment
• Keep your Telegram app open
• Contact support if not approved within 30 minutes
""",
                    parse_mode='HTML'
                )

                break  # Exit retry loop on success
            except Exception as db_error:
                logger.error(f"Database error (attempt {retry_count+1}/{max_retries}): {db_error}")
                logger.error(traceback.format_exc())
                if session:
                    session.rollback()
                if retry_count >= max_retries - 1:
                    raise
                time.sleep(0.5 * (retry_count + 1))  # Progressive delay

        # Send confirmation to user - edit the previous message for faster response
        try:
            bot.edit_message_text(
                f"""
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been successfully activated and you're all set to start shopping on AliExpress using Ethiopian Birr!

<b>📱 Your Services:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance

Need assistance? Use ❓ <b>Help Center</b> anytime!
""",
                chat_id=chat_id,
                message_id=immediate_ack.message_id,
                parse_mode='HTML'
            )

            # Also send the main menu
            bot.send_message(
                chat_id,
                "🏠 Welcome to your new account! What would you like to do?",
                reply_markup=create_main_menu(is_registered=True)
            )
        except Exception as edit_error:
            # If editing fails, send a new message
            logger.error(f"Error editing confirmation message: {edit_error}")
            bot.send_message(
                chat_id,
                """
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been successfully activated and you're all set to start shopping on AliExpress using Ethiopian Birr!

<b>📱 Your Services:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance

Need assistance? Use ❓ <b>Help Center</b> anytime!
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )

        logger.info(f"Registration confirmation sent to user {chat_id}")
        registration_complete = True

        # Clean up registration data only after successful processing
        if chat_id in registration_data:
            del registration_data[chat_id]
        if chat_id in user_states:
            del user_states[chat_id]

        # Record successful registration in performance monitor
        if has_monitor:
            monitor.record_registration("success")

    except Exception as e:
        logger.error(f"Error handling payment: {e}")
        logger.error(traceback.format_exc())

        # Record failed registration in performance monitor
        if has_monitor:
            monitor.record_registration("failure")

        # Send a more helpful error message
        try:
            bot.send_message(
                chat_id, 
                """
❌ <b>There was an error processing your registration.</b>

Don't worry! We've saved your information. Please try again in a few moments or contact support if this persists.
""", 
                parse_mode='HTML'
            )
        except Exception as msg_error:
            logger.error(f"Failed to send error message: {msg_error}")
    finally:
        # Cancel the timeout timer
        registration_timeout.cancel()

        # Always close the session
        safe_close_session(session)

        # Final registration completion check
        if not registration_complete and has_monitor:
            monitor.record_registration("timeout")

@bot.callback_query_handler(func=lambda call: call.data in ["tutorials", "faqs", "sub_benefits"])
def handle_info_buttons(call):
    """Handle information buttons like tutorials, FAQs, and subscription benefits"""
    try:
        if call.data == "tutorials":
            tutorials_msg = """
✨ <b>HOW TO USE ALIPAY_ETH BOT</b> ✨

<b>🔹 STEP 1: REGISTER</b>
• Click 🔑 Register
• Follow the prompts to create your account
• Pay the 350 birr registration fee (200 birr one-time + 150 birr first month)

<b>🔹 STEP 2: DEPOSIT FUNDS</b>
• Click 💰 Deposit
• Choose your deposit amount
• Send payment via CBE or TeleBirr
• Submit screenshot for verification

<b>🔹 STEP 3: PLACE ORDERS</b>
• Find products on AliExpress
• Copy the product link
• Click 📦 Submit Order
• Paste the link and confirm

<b>🔹 STEP 4: TRACK SHIPMENTS</b>
• Click 🔍 Track Order
• Enter your order number
• View status and tracking information

<i>Our system makes shopping on AliExpress simple and hassle-free!</i>
"""
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                tutorials_msg,
                parse_mode='HTML'
            )

        elif call.data == "faqs":
            faqs_msg = """
✨ <b>FREQUENTLY ASKED QUESTIONS</b> ✨

<b>❓ How do I place an order?</b>
Simply click "📦 Submit Order" and paste your AliExpress product link.

<b>❓ How long does shipping take?</b>
Delivery usually takes 15-30 days depending on the product and location.

<b>❓ How do I track my order?</b>
Use the "🔍 Track Order" button and enter your order number.

<b>❓ What payment methods are accepted?</b>
We accept Commercial Bank (CBE) and TeleBirr for deposits.

<b>❓ Is there a minimum order amount?</b>
No, you can order products of any value as long as you have sufficient balance.

<b>❓ How do I renew my subscription?</b>
Click on "📅 Subscription" and use the renewal button.

<i>More questions? Contact our support team!</i>
"""
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                faqs_msg,
                parse_mode='HTML'
            )

        elif call.data == "sub_benefits":
            benefits_msg = """
✨ <b>PREMIUM MEMBERSHIP BENEFITS</b> ✨

<b>🌟 Enjoy these exclusive perks:</b>

• 🛍️ <b>Unlimited Shopping</b>
  Access to thousands of AliExpress products

• 🚚 <b>Priority Shipping</b>
  Faster order processing & delivery

• 💰 <b>Special Discounts</b>
  Member-only deals and promotions

• 🔔 <b>Order Notifications</b>
  Real-time updates on your packages

• 👨‍💼 <b>Dedicated Support</b>
  Premium customer service access

• 🎁 <b>Referral Bonuses</b>
  Earn 50 points (50 birr) for each registration referral

<i>All this for just $1/month!</i>
"""
            bot.answer_callback_query(call.id)
            bot.send_message(
                call.message.chat.id,
                benefits_msg,
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error handling info buttons: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing your request")

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_deposit_') or call.data.startswith('reject_deposit_'))
def handle_deposit_approval_callback(call):
    """Handle deposit approval or rejection callback from inline buttons"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = None

    # Add detailed logging for button clicks
    logger.info(f"Deposit admin button clicked: {call.data}")

    # Check if user is admin
    if not is_admin(chat_id):
        bot.answer_callback_query(call.id, "⛔ You don't have permission to manage deposits")
        return

    try:
        # Parse the callback data with improved reliability
        if call.data.startswith('approve_deposit_'):
            action = 'approve'
            deposit_id = int(call.data.replace('approve_deposit_', ''))
        elif call.data.startswith('reject_deposit_'):
            action = 'reject'
            deposit_id = int(call.data.replace('reject_deposit_', ''))
        else:
            logger.error(f"Unknown deposit action format: {call.data}")
            bot.answer_callback_query(call.id, "Invalid deposit action")
            return
            
        logger.info(f"Parsed deposit action: {action}, deposit_id: {deposit_id}")

        session = get_session()

        # Get deposit and user information
        deposit_info = session.query(PendingDeposit, User).join(User).filter(
            PendingDeposit.id == deposit_id
        ).first()

        if not deposit_info:
            bot.answer_callback_query(call.id, "⚠️ Deposit not found or already processed")
            try:
                bot.edit_message_text(
                    "This deposit has already been processed or was not found.",
                    chat_id=chat_id,
                    message_id=message_id
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
            return

        deposit, user = deposit_info

        # Check if deposit is already processed
        if deposit.status in ['Approved', 'Rejected']:
            bot.answer_callback_query(call.id, f"⚠️ This deposit was already {deposit.status.lower()}")
            try:
                bot.edit_message_text(
                    f"This deposit has already been {deposit.status.lower()}.",
                    chat_id=chat_id,
                    message_id=message_id
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
            return

        # Process approval
        if action == 'approve':
            # Check if this is for subscription renewal
            now = datetime.utcnow()
            subscription_updated = False
            subscription_renewal_msg = ""
            is_for_subscription = False

            # Get user_states to check if deposit was for subscription
            user_telegram_id = user.telegram_id
            if user_telegram_id in user_states and isinstance(user_states[user_telegram_id], dict):
                is_for_subscription = user_states[user_telegram_id].get('for_subscription', False)

            # Check if user has subscription date and if it needs renewal
            if is_for_subscription or (hasattr(user, 'subscription_date') and user.subscription_date and (now - user.subscription_date).days >= 30):
                # Determine if we should deduct subscription fee
                if deposit.amount >= 1.0:  # Only if deposit is at least $1
                    user.balance += (deposit.amount - 1.0)  # Add amount after subscription fee
                    user.subscription_date = now  # Reset subscription date
                    subscription_updated = True

                    if user.subscription_date:
                        subscription_renewal_msg = f"\n<b>📅 SUBSCRIPTION RENEWED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                    else:
                        subscription_renewal_msg = f"\n<b>📅 SUBSCRIPTION ACTIVATED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• Expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"

                    logger.info(f"Subscription {'renewed' if user.subscription_date else 'activated'} for user {user_telegram_id}")
                else:
                    # Deposit too small for subscription, just add to balance
                    user.balance += deposit.amount
                    logger.info(f"Deposit amount ${deposit.amount} too small for subscription renewal")
            else:
                # Regular deposit, just add to balance
                user.balance += deposit.amount

            # Update deposit status
            deposit.status = 'Approved'
            deposit.updated_at = now

            session.commit()
            logger.info(f"Deposit #{deposit_id} of ${deposit.amount:.2f} approved for user {user_telegram_id}")

            # Calculate the birr amount using the current rate
            birr_amount = int(deposit.amount * 160)  # Using 160 ETB = 1 USD

            # Send enhanced fancy confirmation to user
            deposit_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${deposit.amount:.2f}
{f"• Amount after subscription fee: ${deposit.amount - 1.0:.2f}" if subscription_updated else ""}
{subscription_renewal_msg}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
"""

            try:
                bot.send_message(
                    user_telegram_id,
                    deposit_msg,
                    parse_mode='HTML'
                )
            except Exception as send_error:
                logger.error(f"Error sending approval message to user: {send_error}")

            # Update admin message
            try:
                bot.edit_message_text(
                    f"""
<b>Deposit #{deposit.id}</b> - ✅ APPROVED

👤 <b>User:</b> {user.name} [ID: <code>{user.telegram_id}</code>]
💰 <b>Amount:</b> ${deposit.amount:.2f} ({birr_amount:,} birr)
💳 <b>New Balance:</b> ${user.balance:.2f} ({int(user.balance * 160):,} birr)
{f"📅 <b>Subscription:</b> Renewed until {(now + timedelta(days=30)).strftime('%Y-%m-%d')}" if subscription_updated else ""}
⏰ <b>Approved at:</b> {now.strftime("%Y-%m-%d %H:%M")}

<i>User has been notified of the approval.</i>
""",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
            except Exception as edit_error:
                logger.error(f"Error updating admin message: {edit_error}")

            bot.answer_callback_query(call.id, f"✅ Deposit of ${deposit.amount:.2f} approved")

            # Clear user state if necessary
            if user_telegram_id in user_states and isinstance(user_states[user_telegram_id], dict):
                if 'deposit_pending_id' in user_states[user_telegram_id]:
                    del user_states[user_telegram_id]['deposit_pending_id']
                if 'for_subscription' in user_states[user_telegram_id]:
                    del user_states[user_telegram_id]['for_subscription']

        else:  # Reject deposit
            # Update deposit status
            deposit.status = 'Rejected'
            deposit.updated_at = datetime.utcnow()
            session.commit()

            logger.info(f"Deposit #{deposit_id} of ${deposit.amount:.2f} rejected for user {user.telegram_id}")

            # Send rejection notification to user
            try:
                bot.send_message(
                    user.telegram_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❌ <b>DEPOSIT REJECTED</b> ❌  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your deposit of <b>${deposit.amount:.2f}</b> has been rejected.

<b>Possible reasons:</b>
• Payment screenshot not clear
• Payment amount doesn't match
• Payment not found in our records
• Incorrect payment method used

Please try again with a valid payment or contact support if you believe this is an error.

<i>For help, use the "❓ Help Center" option in the main menu</i>
""",
                    parse_mode='HTML'
                )
            except Exception as send_error:
                logger.error(f"Error sending rejection message to user: {send_error}")

            # Update admin message
            try:
                bot.edit_message_text(
                    f"""
<b>Deposit #{deposit.id}</b> - ❌ REJECTED

👤 <b>User:</b> {user.name} [ID: <code>{user.telegram_id}</code>]
💰 <b>Amount:</b> ${deposit.amount:.2f} ({int(deposit.amount * 160):,} birr)
⏰ <b>Rejected at:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}

<i>User has been notified of the rejection.</i>
""",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
            except Exception as edit_error:
                logger.error(f"Error updating admin message: {edit_error}")

            bot.answer_callback_query(call.id, f"❌ Deposit of ${deposit.amount:.2f} rejected")

            # Clear user state if necessary
            if user.telegram_id in user_states and isinstance(user_states[user.telegram_id], dict):
                if 'deposit_pending_id' in user_states[user.telegram_id]:
                    del user_states[user.telegram_id]['deposit_pending_id']
                if 'for_subscription' in user_states[user.telegram_id]:
                    del user_states[user.telegram_id]['for_subscription']

    except Exception as e:
        logger.error(f"Error handling deposit approval callback: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "⚠️ Error processing deposit")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')) and not call.data.startswith(('approve_deposit_', 'reject_deposit_', 'approve_order_', 'reject_order_')))
def handle_admin_decision(call):
    """Handle admin approval/rejection for user registration"""
    session = None
    try:
        parts = call.data.split('_')
        action = parts[0]
        user_id = int(parts[1])
        logger.info(f"Processing {action} for user {user_id}")

        session = get_session()
        pending = session.query(PendingApproval).filter_by(telegram_id=user_id).first()

        if not pending:
            bot.answer_callback_query(call.id, "No pending approval found")
            logger.warning(f"No pending approval found for user_id {user_id}")
            return

        if action == 'approve':
            new_user = User(
                telegram_id=user_id,
                name=pending.name,
                phone=pending.phone,
                address=pending.address,
                balance=0.0,
                subscription_date=datetime.utcnow()
            )
            session.add(new_user)
            session.delete(pending)
            session.commit()

            # Get the ID of the newly created user
            session.refresh(new_user)

            # Process referral if one exists in the registration data
            referral_code = None
            if user_id in registration_data and 'referral_code' in registration_data[user_id]:
                referral_code = registration_data[user_id]['referral_code']
                logger.info(f"Found referral code {referral_code} for user {user_id}")

            # Generate a referral code for the new user first
            try:
                from referral_system import assign_referral_code
                user_referral_code = assign_referral_code(new_user.id)
                logger.info(f"✅ Generated referral code {user_referral_code} for user {user_id}")

                # Refresh to make sure we have the updated record
                session.refresh(new_user)
            except Exception as ref_err:
                logger.error(f"Error generating referral code: {ref_err}")
                logger.error(f"Full error details: {str(ref_err)}")

            # Handle referral code processing
            if referral_code:
                try:
                    from referral_system import check_and_process_registration_referral

                    # Log that we're about to process the referral
                    logger.info(f"Processing referral code {referral_code} for user {new_user.id}")

                    # Use our simplified and fixed referral processing function
                    referral_success = check_and_process_registration_referral(new_user.id, referral_code)

                    if referral_success:
                        logger.info(f"✅ REFERRAL SUCCESS: Successfully processed referral for user {new_user.id} with code {referral_code}")

                        # Also update the user's referred_by_id field to maintain the referral chain
                        try:
                            # Find the referrer directly
                            referrer = session.query(User).filter_by(referral_code=referral_code).first()
                            if referrer and referrer.id != new_user.id:  # Prevent self-referrals
                                new_user.referred_by_id = referrer.id
                                session.commit()
                                logger.info(f"✅ Updated user {new_user.id} with referred_by_id={referrer.id}")
                        except Exception as update_err:
                            logger.error(f"❌ Error updating referred_by_id: {update_err}")
                            # This is not critical, so we continue
                    else:
                        logger.warning(f"❌ Failed to process referral for user {new_user.id} with code {referral_code}")

                        # Fallback method as a last resort
                        try:
                            # Find referrer directly 
                            referrer = session.query(User).filter_by(referral_code=referral_code).first()
                            if referrer and referrer.id != new_user.id:  # Prevent self-referrals
                                # Update points directly with safety checks
                                current_points = referrer.referral_points or 0
                                referrer.referral_points = current_points + 50  # Add registration points

                                # Also update referred_by_id
                                new_user.referred_by_id = referrer.id

                                # Create ReferralReward record
                                from models import ReferralReward
                                new_reward = ReferralReward(
                                    user_id=referrer.id,
                                    points=50,
                                    reward_type='registration',
                                    description=f"Received 50 points for referring a new user"
                                )
                                session.add(new_reward)

                                # Create Referral record
                                from sqlalchemy import and_
                                from models import Referral

                                # Check if referral record exists
                                existing = session.query(Referral).filter(
                                    and_(
                                        Referral.referrer_id == referrer.id,
                                        Referral.referred_id == new_user.id
                                    )
                                ).first()

                                if not existing:
                                    # Create record
                                    new_referral = Referral(
                                        referrer_id=referrer.id,
                                        referred_id=new_user.id,
                                        referral_code=referral_code,
                                        status='completed',
                                        completed_at=datetime.utcnow()
                                    )
                                    session.add(new_referral)

                                # Commit all changes
                                session.commit()
                                logger.info(f"✅ FALLBACK: Successfully added 50 points to referrer {referrer.id}")
                            else:
                                logger.warning(f"❌ Could not find valid referrer with code {referral_code}")
                        except Exception as fallback_err:
                            logger.error(f"❌ Error in fallback referral processing: {fallback_err}")

                except Exception as ref_err:
                    logger.error(f"❌ Error processing referral: {ref_err}")
                    logger.error(f"Full error details: {str(ref_err)}")

            logger.info(f"User {user_id} approved and added to database")

            # Send confirmation to user with enhanced welcome message
            welcome_message = """
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been successfully activated and you're all set to start shopping on AliExpress using Ethiopian Birr!

<b>📱 Your Services:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance
• 🎁 <b>Refer Friends</b> - Earn points and rewards

Need assistance? Use ❓ <b>Help Center</b> anytime!
"""

            # Add referral info if available
            try:
                from referral_system import get_referral_url
                user = session.query(User).filter_by(id=new_user.id).first()
                referral_code = user.referral_code
                if referral_code:
                    referral_url = get_referral_url(referral_code)
                    welcome_message += f"""

<b>🎁 YOUR REFERRAL PROGRAM:</b>
• Your referral code: <code>{referral_code}</code>
• Your referral link: <code>{referral_url}</code>

Share your code or link with friends and earn 50 points for each successful registration!
Each successful referral earns you 50 points that can be converted to account balance (1 point = 1 birr).
"""
            except Exception as ref_err:
                logger.error(f"Error getting referral URL: {ref_err}")

            bot.send_message(
                user_id,
                welcome_message,
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )

            # Tutorial functionality has been completely removed
            logger.info(f"✅ Registration complete for user {user_id} - not offering tutorial (disabled)")

            # Update admin message
            bot.edit_message_text(
                f"✅ Registration for {pending.name} approved successfully!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        elif action == 'reject':
            session.delete(pending)
            session.commit()
            logger.info(f"Registration for user {user_id} rejected")

            bot.send_message(
                user_id,
                """
❌ <b>Registration Declined</b>

We could not verify your payment. Please ensure:
• You sent the correct amount
• The screenshot is clear
• Payment was to correct account

Please try registering again.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=False)
            )

            bot.edit_message_text(
                f"❌ Registration for {pending.name} rejected!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        # Ensure we answer the callback query to remove loading indicator
        bot.answer_callback_query(call.id, text="Action processed successfully")

    except Exception as e:
        logger.error(f"Error in admin decision: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing decision")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '💰 Deposit')
@subscription_required
def deposit_funds(message):
    """Handle deposit button"""
    return deposit_funds_internal(message, for_subscription=False)

def deposit_funds_internal(message, for_subscription=False):
    """Internal deposit handler with subscription renewal option"""
    chat_id = message.chat.id
    # Store the subscription flag in user states
    if for_subscription:
        if chat_id not in user_states:
            user_states[chat_id] = {}
        elif not isinstance(user_states[chat_id], dict):
            user_states[chat_id] = {}
        user_states[chat_id]['for_subscription'] = True
    deposit_msg = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>CHOOSE DEPOSIT AMOUNT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Select how much you'd like to deposit:
"""
    menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    menu.add(
        KeyboardButton('$5 (800 birr)'),
        KeyboardButton('$10 (1,600 birr)')
    )
    menu.add(
        KeyboardButton('$15 (2,400 birr)'),
        KeyboardButton('$20 (3,200 birr)')
    )
    menu.add(KeyboardButton('Customize'))
    menu.add(KeyboardButton('Back to Main Menu'))

    bot.send_message(chat_id, deposit_msg, reply_markup=menu, parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text in ['$5 (800 birr)', '$10 (1,600 birr)', '$15 (2,400 birr)', '$20 (3,200 birr)', 'Customize', 'Back to Main Menu'])
def handle_deposit_amount(message):
    """Handle deposit amount selection"""
    chat_id = message.chat.id

    if message.text == 'Back to Main Menu':
        # Check if user is registered
        session = None
        try:
            session = get_session()
            user = session.query(User).filter_by(telegram_id=chat_id).first()
            is_registered = user is not None

            # Return to main menu
            bot.send_message(
                chat_id,
                "🏠 Returning to main menu...",
                reply_markup=create_main_menu(is_registered=is_registered)
            )

            # Clear any existing state
            if chat_id in user_states:
                del user_states[chat_id]
        except Exception as e:
            logger.error(f"Error returning to main menu: {e}")
            bot.send_message(chat_id, "🏠 Back to main menu", reply_markup=create_main_menu(is_registered=True))
        finally:
            safe_close_session(session)
        return

    if message.text == 'Customize':
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>CUSTOM DEPOSIT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Enter amount in <b>USD</b> or <b>birr</b>.
Examples:
• Enter <code>$10</code> for $10 (1,600 birr)
• Enter <code>1600</code> for 1,600 birr ($10)

<i>You can optionally include $ or "usd" for dollar amounts.</i>
""",
            parse_mode='HTML'
        )
        user_states[chat_id] = 'waiting_for_custom_amount'
        return

    # Extract amount from button text - handles format like "$5 (800 birr)"
    if '(' in message.text and ')' in message.text:
        # Extract dollar amount from the start of the string
        amount_text = message.text.split('(')[0].strip()
        # Remove $ and convert to float
        amount = float(amount_text.replace('$', ''))
        # Use dollar amount for payment
        # Check if this is for subscription renewal
        for_subscription = False
        if chat_id in user_states and isinstance(user_states[chat_id], dict) and user_states[chat_id].get('for_subscription'):
            for_subscription = True

        payment_details(message, amount, for_subscription)  # Call with subscription flag

def send_payment_details(message, amount, for_subscription=False):
    """Send payment details to user"""
    payment_details(message, amount, for_subscription)  # Call the existing payment_details function with subscription flag

def payment_details(message, amount, for_subscription=False):
    """Send payment instructions with Chapa integration"""
    chat_id = message.chat.id
    birr_amount = int(float(amount) * 160)
    session = None

    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id, 
                "❌ You need to register first before making a deposit.", 
                reply_markup=create_main_menu(is_registered=False)
            )
            return

        # Import Chapa payment module
        from chapa_payment import generate_deposit_payment

        # Create user data dict for payment
        user_data = {
            'telegram_id': chat_id,
            'name': user.name,
            'phone': user.phone
        }

        # Add subscription flag if this is a subscription renewal
        if for_subscription:
            user_data['for_subscription'] = True
            logger.info(f"Creating payment for subscription renewal, user: {chat_id}")

        # Generate payment link
        payment_link = generate_deposit_payment(user_data, amount)

        if not payment_link or 'checkout_url' not in payment_link:
            # Fall back to manual payment if Chapa fails
            user_states[chat_id] = {
                'state': 'waiting_for_deposit_screenshot',
                'deposit_amount': amount
            }

            payment_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💸 <b>DEPOSIT DETAILS</b> 💸  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💵 AMOUNT TO PAY:</b>
• <code>{birr_amount:,}</code> birr
• (${amount:.2f} USD)

<b>💳 PAYMENT METHODS 💳</b>

<b>🏦 COMMERCIAL BANK (CBE)</b>
• Account: <code>1000547241316</code>
• Name: <code>Eyob Mulugeta</code>

<b>📱 TELEBIRR</b>
• Number: <code>0986693062</code>
• Name: <code>Eyob Mulugeta</code>

<b>📸 HOW TO PROCEED 📸</b>
1️⃣ Choose your preferred payment method
2️⃣ Transfer <b>exactly</b> <code>{birr_amount:,} birr</code>
3️⃣ Take a clear screenshot of payment confirmation
4️⃣ Send the screenshot below ⬇️

<i>✨ Your balance will be updated immediately after verification! ✨</i>
"""
            bot.send_message(chat_id, payment_msg, parse_mode='HTML')
        else:
            # Use Chapa payment link with inline button
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("💳 PAY NOW 💳", url=payment_link['checkout_url']))

            payment_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💸 <b>SECURE DEPOSIT</b> 💸  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 PAYMENT AMOUNT:</b>
• <code>{birr_amount:,}</code> birr
• (${amount:.2f} USD)

<b>✨ INSTANT PAYMENT OPTIONS ✨</b>

<b>Click the button below to pay securely with:</b>
• TeleBirr
• CBE Birr
• HelloCash
• Amole
• Credit/Debit Cards
• And more!

<i>✅ AUTO-APPROVAL: Your balance will update automatically within 1 minute of successful payment!</i>
<i>No manual approval needed - no screenshots required</i>
"""
            bot.send_message(chat_id, payment_msg, parse_mode='HTML', reply_markup=markup)

            # Store transaction reference for automatic verification
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Processing',
                tx_ref=payment_link['tx_ref'],  # Save the transaction reference for automatic verification
                created_at=datetime.utcnow()
                # Note: updated_at removed as it's not in the PendingDeposit model
            )
            session.add(pending_deposit)
            session.commit()

            logger.info(f"✅ Created deposit record with tx_ref: {payment_link['tx_ref']} for user {chat_id}")
            logger.info(f"👍 Deposit will be auto-approved by system within 1 minute of successful payment")

            # Update user state
            user_states[chat_id] = {
                'state': 'waiting_for_chapa_payment',
                'tx_ref': payment_link['tx_ref'],
                'deposit_amount': amount
            }
    except Exception as e:
        logger.error(f"Error generating payment details: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error processing your request. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_custom_amount')
def process_custom_amount(message):
    """Process custom deposit amount in birr"""
    chat_id = message.chat.id
    try:
        # Check if user entered birr or USD amount
        amount_text = message.text.strip()

        # Remove any non-numeric characters
        clean_amount = ''.join(c for c in amount_text if c.isdigit() or c == '.')

        # Determine if the amount is in USD or birr based on user input
        is_usd = '$' in amount_text or 'usd' in amount_text.lower() or 'dollar' in amount_text.lower()

        if is_usd:
            # User entered USD, store as USD
            usd_amount = float(clean_amount)
            birr_amount = int(usd_amount * 160.0)
        else:
            # User entered birr, convert to USD
            birr_amount = int(float(clean_amount))
            usd_amount = birr_amount / 160.0

        # Check if amount is reasonable
        if birr_amount < 100:
            bot.send_message(
                chat_id,
                """
❌ <b>Amount Too Small</b>

Please enter an amount of at least 100 birr.
""",
                parse_mode='HTML'
            )
            return

        if birr_amount > 100000:
            bot.send_message(
                chat_id,
                """
❌ <b>Amount Too Large</b>

Please enter an amount less than 100,000 birr.
For larger deposits, please contact support.
""",
                parse_mode='HTML'
            )
            return

        # Send payment details with the custom amount
        # Check if this is for subscription renewal
        for_subscription = False
        if chat_id in user_states and isinstance(user_states[chat_id], dict) and user_states[chat_id].get('for_subscription'):
            for_subscription = True

        send_payment_details(message, usd_amount, for_subscription)

    except ValueError:
        bot.send_message(
            chat_id,
            """
❌ <b>Invalid Amount</b>

Please enter a valid number (birr amount).
Example: <code>2000</code> for 2,000 birr
""",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error processing custom amount: {e}")
        bot.send_message(
            chat_id,
            "Sorry, there was an error. Please try again.",
            reply_markup=create_main_menu(is_registered=True)
        )

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and isinstance(user_states[msg.chat.id], dict) and user_states[msg.chat.id].get('state') == 'waiting_for_deposit_screenshot', content_types=['photo'])
def handle_deposit_screenshot(message):
    """Process deposit screenshot with secure verification"""
    chat_id = message.chat.id
    session = None
    try:
        file_id = message.photo[-1].file_id

        # Make sure we have valid deposit data in user state
        if chat_id not in user_states or not isinstance(user_states[chat_id], dict) or 'deposit_amount' not in user_states[chat_id]:
            logger.error(f"Missing deposit data for user {chat_id}")
            bot.send_message(chat_id, "Missing deposit information. Please start your deposit again.")
            return

        deposit_amount = user_states[chat_id].get('deposit_amount', 0)
        birr_amount = int(deposit_amount * 160)  # Updated ETB conversion rate

        # Verify user exists in database
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(chat_id, "Please register first before making a deposit.")
            return

        # Check if this is for subscription renewal
        is_for_subscription = False
        if isinstance(user_states[chat_id], dict) and user_states[chat_id].get('for_subscription'):
            is_for_subscription = True

        # First acknowledge receipt of screenshot
        immediate_ack = bot.send_message(
            chat_id,
            "📸 Screenshot received! Processing your deposit...",
            parse_mode='HTML'
        )

        # Create pending deposit record for manual verification
        pending_deposit = PendingDeposit(
            user_id=user.id,
            amount=deposit_amount,
            status='Pending Manual Verification',
            created_at=datetime.utcnow()
        )
        session.add(pending_deposit)
        session.commit()

        # Get the ID of the newly created pending deposit
        session.refresh(pending_deposit)
        deposit_id = pending_deposit.id

        logger.info(f"Created pending deposit #{deposit_id} of ${deposit_amount} for user {chat_id}")

        # Notify admin about deposit that needs approval
        admin_msg = f"""
⏳ <b>DEPOSIT NEEDS VERIFICATION</b>

User Details:
Name: <b>{user.name}</b>
ID: <code>{chat_id}</code>
Phone: <code>{user.phone}</code>

Amount:
USD: <code>${deposit_amount:,.2f}</code>
ETB: <code>{birr_amount:,}</code>

Current Balance: <code>${user.balance:.2f}</code>
{f"Subscription Status: {'Active' if user.subscription_date and (datetime.utcnow() - user.subscription_date).days < 30 else 'Expired or Not Active'}" if hasattr(user, 'subscription_date') else ""}
{f"For Subscription Renewal: Yes" if is_for_subscription else ""}

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Screenshot attached below
"""
        if ADMIN_ID:
            try:
                bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')
                bot.send_photo(ADMIN_ID, file_id, caption="📸 Deposit Screenshot For Verification")

                # Send approval buttons to admin
                approve_markup = InlineKeyboardMarkup()
                approve_markup.row(
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_deposit_{deposit_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_deposit_{deposit_id}")
                )

                bot.send_message(
                    ADMIN_ID,
                    f"Admin action needed for deposit #{deposit_id}:",
                    reply_markup=approve_markup
                )
            except Exception as admin_error:
                logger.error(f"Error notifying admin about deposit: {admin_error}")

        # Send pending verification message to user
        # Edit the immediate acknowledgment for a faster response
        try:
            bot.edit_message_text(
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ⏳ <b>DEPOSIT PENDING</b> ⏳  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${deposit_amount:.2f}
{f"• This will also renew your subscription" if is_for_subscription else ""}

<b>📋 VERIFICATION STATUS:</b>
• Your deposit is currently pending verification
• Typically verified within 10-15 minutes
• You'll receive notification once approved

<b>📞 NEED ASSISTANCE?</b>
• Contact our support team if not verified within 30 minutes

<i>Thank you for your patience!</i>
""",
                chat_id=chat_id,
                message_id=immediate_ack.message_id,
                parse_mode='HTML'
            )
        except Exception as edit_error:
            # If editing fails, send a new message
            logger.error(f"Error editing confirmation message: {edit_error}")
            bot.send_message(
                chat_id,
                """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ⏳ <b>DEPOSIT PENDING</b> ⏳  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Your deposit is being processed
• Typically verified within 10-15 minutes
• You'll receive a notification once approved

<i>Thank you for your patience!</i>
""",
                parse_mode='HTML'
            )

        # Store deposit information for verification
        if chat_id not in user_states:
            user_states[chat_id] = {}
        user_states[chat_id]['deposit_pending_id'] = deposit_id

    except Exception as e:
        logger.error(f"Error processing deposit: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error processing your deposit. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '💳 Balance')
@subscription_required
def check_balance(message):
    """Check user balance with referral badges and hover effects"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if user:
            # Default to 0 if balance is None
            balance = user.balance if user.balance is not None else 0
            birr_balance = int(balance * 160.0)  # Use correct ETB/USD rate (1 USD = 160 ETB)

            # Get referral points
            points_balance = user.referral_points or 0

            # Get user badge with hover effect
            try:
                from referral_system import generate_badge_html
                badge_html = generate_badge_html(user.id)
            except Exception as badge_err:
                logger.error(f"Error generating badge: {badge_err}")
                badge_html = ""

            # Get referral count
            referral_count = 0
            try:
                from sqlalchemy import text
                query = text("""
                SELECT COUNT(*) as count
                FROM referrals
                WHERE referrer_id = :user_id
                """)
                result = session.execute(query, {'user_id': user.id}).fetchone()
                referral_count = result.count if result else 0
            except Exception as ref_err:
                logger.error(f"Error counting referrals: {ref_err}")

            # Enhanced balance display without referral points
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>YOUR ACCOUNT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Available Balance:</b> <code>{birr_balance:,}</code> birr
≈ $<code>{balance:,.2f}</code> USD

<i>Referral system coming soon!</i>



<i>Need more balance? Click 💰 Deposit</i>
""",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error checking balance:{e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '🏆 Referral Badges (Coming Soon)')
@subscription_required
def referral_badges(message):
    """Display referral badges coming soon message"""
    chat_id = message.chat.id

    # Display coming soon message
    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🏆 <b>REFERRAL BADGES</b> 🏆  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>This feature is coming soon!</b>

Our referral system is currently under development and will be available soon.
You'll be able to invite friends and earn rewards.

<i>Stay tuned for updates!</i>
""",
        parse_mode='HTML',
        reply_markup=create_main_menu(is_registered=True, chat_id=chat_id)
    )

@bot.message_handler(func=lambda msg: msg.text == '🔗 My Referral Link (Coming Soon)')
@subscription_required
def my_referral_link(message):
    """Handle My Referral Link button to display coming soon message"""
    chat_id = message.chat.id

    # Display coming soon message
    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔗 <b>REFERRAL LINK</b> 🔗  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>This feature is coming soon!</b>

Our referral system is currently under development and will be available soon.
You'll be able to invite friends with your personal referral link and earn rewards.

<i>Stay tuned for updates!</i>
""",
        parse_mode='HTML',
        reply_markup=create_main_menu(is_registered=True, chat_id=chat_id)
    )

@bot.message_handler(func=lambda msg: msg.text == '👥 Join Community')
def join_community(message):
    """Join community button"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 Our Channel", url="https://t.me/alipay_eth"))
    markup.add(InlineKeyboardButton("👥 Our Group", url="https://t.me/aliexpresstax"))

    bot.send_message(
        message.chat.id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👥 <b>JOIN OUR COMMUNITY!</b> 👥  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Stay Connected With Us!</b>

📢 <b>Our Channel:</b> Get the latest updates, promotions, and announcements directly from our team.

👥 <b>Our Group:</b> Connect with other users, share experiences, and get community support.

<i>Join both for the complete AliPay_ETH experience!</i>
""",
        parse_mode='HTML',
        reply_markup=markup
    )

@bot.message_handler(func=lambda msg: msg.text == '📦 Submit Order')
@subscription_required
def submit_order(message):
    """Handle submit order button with enhanced UI"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id, 
                """
⚠️ <b>Registration Required</b>

You need to register first before placing orders.
Click 🔑 Register to create your account.
""", 
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=False)
            )
            return

        # Check if user has enough balance
        if user.balance is None or user.balance <= 0:
            bot.send_message(
                chat_id,
                """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❌ <b>INSUFFICIENT BALANCE</b> ❌  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 Your current balance:</b> $0.00

You need to add funds to your account before placing an order. 
Click 💰 <b>Deposit</b> to add funds and start shopping!

<i>Our payment options include CBE and TeleBirr for your convenience.</i>
""",
                parse_mode='HTML'
            )
            return

        # Start order submission process with a fancy animated-like message
        user_states[chat_id] = 'waiting_for_order_link'

        # Create inline keyboard with Back button
        back_markup = ReplyKeyboardMarkup(resize_keyboard=True)
        back_markup.add(KeyboardButton('Back to Main Menu'))

        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🛍️ <b>NEW ALIEXPRESS ORDER</b> 🛍️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 Your current balance:</b> $<code>{:.2f}</code>

<b>🔍 HOW TO ORDER:</b>

1️⃣ Go to AliExpress and find your product
2️⃣ Copy the complete product URL
3️⃣ Paste the link below
4️⃣ Our team will process your order immediately

<b>✨ PASTE YOUR LINK BELOW:</b>

Example:
<code>https://www.aliexpress.com/item/12345.html</code>

<i>💫 We handle everything for you - payment, shipping, and tracking! 💫</i>

Press 'Back to Main Menu' to cancel your order.
""".format(user.balance),
            parse_mode='HTML',
            reply_markup=back_markup
        )
    except Exception as e:
        logger.error(f"Error in submit order: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_order_link')
def process_order_link(message):
    """Process the order link with enhanced UI and reliability"""
    chat_id = message.chat.id
    link = message.text.strip()
    session = None

    # Handle "Back to Main Menu" request
    if link == 'Back to Main Menu':
        try:
            session = get_session()
            user = session.query(User).filter_by(telegram_id=chat_id).first()
            is_registered = user is not None

            # Clear the state and return to main menu
            if chat_id in user_states:
                del user_states[chat_id]

            bot.send_message(
                chat_id,
                "🏠 Order cancelled. Returning to main menu...",
                reply_markup=create_main_menu(is_registered=is_registered)
            )
            return
        except Exception as e:
            logger.error(f"Error returning to main menu: {e}")
            if chat_id in user_states:
                del user_states[chat_id]
            bot.send_message(chat_id, "🏠 Back to main menu", reply_markup=create_main_menu(is_registered=True))
            return
        finally:
            safe_close_session(session)

    # First, send immediate acknowledgement
    processing_msg = bot.send_message(
        chat_id,
        "⏳ <b>Processing your order...</b>",
        parse_mode='HTML'
    )

    # Pre-process AliExpress shared links which might be in the format:
    # "3.54|product name https://aliexpress.com/..."
    # Check for AliExpress link pattern in the message
    if 'aliexpress' in link.lower():
        # If it contains aliexpress but doesn't start with http,
        # try to extract the URL from the shared format
        if not link.startswith('http'):
            import re
            # Pattern to match URLs
            url_pattern = r'https?://[^\s]+'
            urls = re.findall(url_pattern, link)
            if urls:
                # Extract the actual URL from the message
                link = urls[0]
                logger.info(f"Extracted AliExpress URL from shared message: {link}")
            else:
                # Handle cases where URL might be formatted differently
                parts = link.split('http')
                if len(parts) > 1:
                    link = 'http' + parts[1]
                    logger.info(f"Extracted URL by splitting: {link}")

    # Fallback validation - still check if it's a valid link
    if not link.startswith('http') or 'aliexpress' not in link.lower():
        bot.edit_message_text(
            """
❌ <b>INVALID LINK DETECTED</b>

Please provide a valid AliExpress product link. 
I can process links in these formats:
• Standard URL: <code>https://www.aliexpress.com/item/...</code>
• AliExpress share format: <code>3.54|Product Name https://aliexpress.com/...</code>

The link must contain 'aliexpress' in the URL.
Please try again or press 'Back to Main Menu' to cancel.
""",
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            parse_mode='HTML'
        )
        return

    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        # Get user's order count to generate order number
        order_count = session.query(Order).filter_by(user_id=user.id).count()
        new_order_number = order_count + 1

        # Create new order with processing status
        new_order = Order(
            user_id=user.id,
            order_number=new_order_number,
            product_link=link,
            status='Processing',
            amount=0.0  # Will be updated by admin when processing
        )
        session.add(new_order)
        session.commit()

        # Extract product title from link for better display (if possible)
        product_display = link.split('/item/')[-1].split('.html')[0] if '/item/' in link else "AliExpress Product"

        # Notify admin about the new order with improved formatting
        admin_markup = InlineKeyboardMarkup()
        admin_markup.row(
            InlineKeyboardButton("✅ Process", callback_data=f"process_order_{new_order.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_order_{new_order.id}")
        )
        admin_markup.row(
            InlineKeyboardButton("🔗 View Product", url=link)
        )

        admin_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🛍️ <b>NEW ORDER RECEIVED</b> 🛍️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📋 CUSTOMER DETAILS:</b>
• Name: <b>{user.name}</b>
• Phone: <code>{user.phone}</code>
• Address: {user.address}
• User ID: <code>{chat_id}</code>

<b>💰 FINANCIAL DETAILS:</b>
• Balance: $<code>{user.balance:.2f}</code>
• Order #: <code>{new_order_number}</code>

<b>🔗 PRODUCT LINK:</b>
<a href="{link}">{link}</a>

<b>⏰ TIME:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<i>Please review and process this order</i>
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)

        # Calculate remaining balance
        remaining_balance = user.balance
        birr_balance = int(remaining_balance * 160.0)  # Convert to birr (1 USD = 160 ETB)

        # Notify user about order submission with enhanced beautiful design
        bot.edit_message_text(
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🎉 <b>ORDER PLACED SUCCESSFULLY!</b> 🎉  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

✨ Your AliExpress order request has been received! ✨

<b>📦 ORDER DETAILS:</b>
• Order Number: <code>{new_order_number}</code>
• Status: <b>Processing</b>
• Time: {datetime.now().strftime('%I:%M %p, %d %b %Y')}

<b>💰 ACCOUNT BALANCE:</b>
• Remaining: <code>{birr_balance:,}</code> birr (${remaining_balance:.2f})

<b>🔍 TRACK YOUR ORDER:</b>
1️⃣ Click "<b>🔍 Track Order</b>" in menu
2️⃣ Enter Order #: <code>{new_order_number}</code>

<b>📱 ORDER UPDATES:</b>
• Processing ⏳
• Confirmation ✅
• Shipping 🚚
• Delivery 📦

<i>We'll notify you of all status changes!</i>

<b>Need help?</b> Use ❓ Help Center anytime!

<i>Thank you for shopping with AliPay_ETH!</i>
""",
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            parse_mode='HTML'
        )

        # Send main menu
        bot.send_message(
            chat_id,
            "What would you like to do next?",
            reply_markup=create_main_menu(is_registered=True)
        )

        # Reset user state
        del user_states[chat_id]

    except Exception as e:
        logger.error(f"Error processing order link: {e}")
        logger.error(traceback.format_exc())
        try:
            bot.edit_message_text(
                """
❌ <b>ERROR PROCESSING ORDER</b>

Sorry, we encountered an error while processing your order. 
Please try again in a few moments.

If the issue persists, please contact our support team.
""",
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                parse_mode='HTML'
            )
        except Exception:
            # Fallback if edit fails
            bot.send_message(
                chat_id,
                "Sorry, there was an error. Please try again.",
                reply_markup=create_main_menu(is_registered=True)
            )
    finally:
        # Always clean up
        safe_close_session(session)
        if chat_id in user_states:
            del user_states[chat_id]

# This handler has been replaced with the consolidated version at line 1309
# All code has been removed from this duplicate handler to fix button conflicts

@bot.message_handler(func=lambda msg: msg.text == '🔍 Track Order')
@subscription_required
def track_order(message):

@bot.message_handler(func=lambda msg: msg.text == '🔍 Track Order')
@subscription_required
def track_order(message):
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id, 
                """
⚠️ <b>REGISTRATION REQUIRED</b>

Please register first to track orders.
You can register by clicking 🔑 Register on the main menu.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu()
            )
            return

        # Ask for order number with better description of what they'll get
        msg = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>DETAILED ORDER TRACKING</b> 🔍  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Enter your order number to see:
• 📊 Comprehensive order details
• 📦 Real-time shipping status
• 🚚 Estimated delivery dates
• 🛍️ Product information
• 📬 Tracking links and updates

Please enter the order number you want to track:
Example: <code>12345</code>
"""
        bot.send_message(chat_id, msg, parse_mode='HTML')
        user_states[chat_id] = 'waiting_for_order_number'
    except Exception as e:
        logger.error(f"Error in track order: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id, 
            """
We're sorry, but there was a technical issue processing your request.
Please try again or contact support if the problem persists.

You can use 📊 <b>Order Status</b> to view all your orders instead.
""",
            parse_mode='HTML',
            reply_markup=create_main_menu(is_registered=True)
        )
    finally:
        if session:
            safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_order_number')
def process_order_number(message):
    """Process order number for detailed tracking with comprehensive information"""
    chat_id = message.chat.id
    session = None
    try:
        order_number = message.text.strip()

        # Reset state
        user_states[chat_id] = None

        # Check if order number is valid
        if not order_number.isdigit():
            bot.send_message(
                chat_id,
                """
❌ <b>INVALID ORDER NUMBER</b>

Please enter a valid order number (digits only).
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )
            return

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        order = session.query(Order).filter_by(user_id=user.id, order_number=int(order_number)).first()

        if not order:
            bot.send_message(
                chat_id,
                f"""
❌ <b>ORDER NOT FOUND</b>

We couldn't find order #{order_number} in your account.
Please check the order number and try again.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )
            return

        # Format status with emoji
        status_emoji = "⏳"
        status_color = "🟡"
        if order.status == "Completed":
            status_emoji = "✅"
            status_color = "🟢"
        elif order.status == "Cancelled":
            status_emoji = "❌"
            status_color = "🔴"
        elif order.status == "Processing":
            status_emoji = "🔄"
            status_color = "🔵"
        elif order.status == "Shipped":
            status_emoji = "🚚"
            status_color = "🟢"

        # Create comprehensive tracking information if tracking number exists
        tracking_info = ""
        delivery_estimate = ""
        if order.tracking_number:
            clean_tracking = order.tracking_number.strip().replace(" ", "").replace("+", "%20")
            parcels_app_link = f"https://global.cainiao.com/detail.htm?mailNo={clean_tracking}&lang=en"
            aliexpress_tracking_link = f"https://aliexpress.com/trackOrder.htm"
            tracking_info = f"""
<b>📬 TRACKING INFORMATION:</b>
• Tracking Number: <code>{order.tracking_number}</code>
• Carrier: <b>{"Standard AliExpress Shipping" if not order.carrier else order.carrier}</b>

<b>📱 TRACKING LINKS:</b>
• <a href="{parcels_app_link}">🌎 Track Package on Cainiao </a> (Real-time global updates)
• <a href="{aliexpress_tracking_link}">🛒 Track on AliExpress</a> (Official tracking)
"""
            # Calculate estimated delivery date (between 15-30 days from order date for shipped orders)
            if order.status == "Shipped":
                min_delivery_date = order.created_at + timedelta(days=15)
                max_delivery_date = order.created_at + timedelta(days=30)
                today = datetime.utcnow()

                if today > max_delivery_date:
                    delivery_estimate = f"""
<b>📅 DELIVERY STATUS:</b>
• Package may be delayed
• Expected to arrive soon
• Contact support if not received within 5 days
"""
                else:
                    delivery_estimate = f"""
<b>📅 ESTIMATED DELIVERY:</b>
• Earliest: <b>{min_delivery_date.strftime('%d %b %Y')}</b>
• Latest: <b>{max_delivery_date.strftime('%d %b %Y')}</b>
• Status updates may take 1-2 days to appear
"""

        # Create order message with enhanced design and more detailed information
        order_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>DETAILED ORDER TRACKING</b> 🔍  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📋 ORDER INFORMATION:</b>
• Order: <b>#{order.order_number}</b>
• Status: {status_emoji} <b>{order.status}</b> {status_color}
• Amount: <b>${order.amount:.2f}</b>
• Date Ordered: <b>{order.created_at.strftime('%d %b %Y')}</b>
"""

        if order.order_id:
            order_msg += f"""
<b>🔖 ALIEXPRESS DETAILS:</b>
• Order ID: <code>{order.order_id}</code>
• Seller: <b>AliExpress Merchant</b>
• Payment Method: <b>Processed by AliPay_ETH</b>
"""

        # Add tracking info if available
        if tracking_info:
            order_msg += f"\n{tracking_info}"

        # Add delivery estimate if available
        if delivery_estimate:
            order_msg += f"\n{delivery_estimate}"

        # Add shipping status timeline
        shipping_timeline = f"""
<b>📦 SHIPPING STATUS TIMELINE:</b>
• <b>Order Placed:</b> {order.created_at.strftime('%d %b %Y')}
"""
        if order.status == "Processing" or order.status == "Shipped" or order.status == "Completed":
            shipping_timeline += f"• <b>Processing Started:</b> {(order.created_at + timedelta(days=1)).strftime('%d %b %Y')}\n"

        if order.status == "Shipped" or order.status == "Completed":
            shipping_date = order.created_at + timedelta(days=3)
            shipping_timeline += f"• <b>Package Shipped:</b> {shipping_date.strftime('%d %b %Y')}\n"

        if order.status == "Completed":
            completion_date = order.created_at + timedelta(days=25)
            shipping_timeline += f"• <b>Delivered:</b> {completion_date.strftime('%d %b %Y')}\n"

        order_msg += f"\n{shipping_timeline}"

        # Add detailed product information
        if order.product_link:
            product_name = "AliExpress Product"
            order_msg += f"""
<b>🛍️ PRODUCT INFORMATION:</b>
• Name: <b>{product_name}</b>
• <a href="{order.product_link}">View Product on AliExpress</a>
• Quantity: <b>1</b> item(s)
"""

        # Add shipping address information if available
        session2 = get_session()
        try:
            user_with_address = session2.query(User).filter_by(id=order.user_id).first()
            if user_with_address and user_with_address.address:
                order_msg += f"""
<b>🏠 SHIPPING ADDRESS:</b>
• Destination: <b>{user_with_address.address}</b>
"""
        finally:
            safe_close_session(session2)

        # Add support information
        order_msg += f"""
<b>📞 NEED HELP?</b>
• For delivery issues: Contact us after {(order.created_at + timedelta(days=35)).strftime('%d %b %Y')}
• For urgent assistance: Contact @alipay_help_center

<i>💫 Thank you for shopping with AliPay_ETH! 💫</i>
"""

        bot.send_message(
            chat_id,
            order_msg,
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=create_main_menu(is_registered=True)
        )
    except Exception as e:
        logger.error(f"Error tracking order: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            """
We're sorry, but there was a technical issue processing your request.
Please try again or contact support if the problem persists.
""",
            parse_mode='HTML',
            reply_markup=create_main_menu(is_registered=True)
        )
    finally:
        if session:
            safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '📊 Order Status')
@subscription_required
def order_status(message):
    """Handle order status button with simplified overview"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        if not user:
            bot.send_message(
                chat_id, 
                """
⚠️ <b>REGISTRATION REQUIRED</b>

Please register first to check order status.
You can register by clicking 🔑 Register on the main menu.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu()
            )
            return

        # Get user orders
        orders = session.query(Order).filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()

        if not orders:
            bot.send_message(
                chat_id,
                """
📊 <b>ORDER STATUS</b>

You don't have any orders yet.
To place an order, click 📦 <b>Submit Order</b> from the main menu.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )
            return

        # Show all orders with simplified formatting - BASIC INFORMATION ONLY
        orders_text = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>ORDER STATUS OVERVIEW</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Your orders at a glance:</b>
"""
        # Counters for different statuses
        pending_count = 0
        processing_count = 0
        shipped_count = 0
        completed_count = 0
        cancelled_count = 0

        # Process order status counts
        for order in orders:
            if order.status == "Pending":
                pending_count += 1
            elif order.status == "Processing":
                processing_count += 1
            elif order.status == "Shipped":
                shipped_count += 1
            elif order.status == "Completed":
                completed_count += 1
            elif order.status == "Cancelled":
                cancelled_count += 1

        # Status summary section
        orders_text += f"""
<b>📈 SUMMARY:</b>
• ⏳ Pending: {pending_count}
• 🔄 Processing: {processing_count}
• 🚚 Shipped: {shipped_count}
• ✅ Completed: {completed_count}
• ❌ Cancelled: {cancelled_count}

<b>📋 RECENT ORDERS:</b>
"""

        # Only show basic details for the 5 most recent orders
        recent_orders = orders[:5]
        for order in recent_orders:
            status_emoji = "⏳"
            if order.status == "Completed":
                status_emoji = "✅"
            elif order.status == "Cancelled":
                status_emoji = "❌"
            elif order.status == "Processing":
                status_emoji = "🔄"
            elif order.status == "Shipped":
                status_emoji = "🚚"

            # Simple, concise order entry
            order_details = f"""• #{order.order_number} - {status_emoji} {order.status} - {order.created_at.strftime('%d %b %Y')}"""
            orders_text += f"\n{order_details}"

        orders_text += """

<b>🔍 FOR DETAILED TRACKING:</b>
• Use 🔍 <b>Track Order</b> button and enter your order number
• This will show detailed product info and shipping status

<i>💫 Thank you for shopping with AliPay_ETH! 💫</i>
"""

        bot.send_message(
            chat_id,
            orders_text,
            parse_mode='HTML',
            reply_markup=create_main_menu(is_registered=True)
        )
    except Exception as e:
        logger.error(f"Error in order status: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "Sorry, there was an error retrieving your orders. Please try again later.",
            reply_markup=create_main_menu(is_registered=True)
        )
    finally:
        if session:
            safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith('process_order_') or call.data.startswith('reject_order_'))
def handle_order_admin_decision(call):
    """Handle admin approval/rejection for orders with enhanced user notifications"""
    session = None
    try:
        # Add detailed logging for button clicks to help with debugging
        logger.info(f"Order admin button clicked: {call.data}")
        
        # More robust parsing of callback data to handle both formats reliably
        if call.data.startswith('process_order_'):
            action = 'process'
            order_id = int(call.data.replace('process_order_', ''))
        elif call.data.startswith('reject_order_'):
            action = 'reject'
            order_id = int(call.data.replace('reject_order_', ''))
        else:
            logger.error(f"Unknown order action format: {call.data}")
            bot.answer_callback_query(call.id, "Invalid order action")
            return
            
        logger.info(f"Parsed order action: {action}, order_id: {order_id}")

        session = get_session()
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            bot.answer_callback_query(call.id, "Order not found.")
            return

        user = session.query(User).filter_by(id=order.user_id).first()

        if action == 'process':
            # Update order status
            order.status = 'Processing'
            order.updated_at = datetime.utcnow()
            session.commit()

            # Ask for order details
            bot.answer_callback_query(call.id, "Please provide order details")
            msg = bot.send_message(
                call.message.chat.id,
                """
Please provide the following order details:

1. AliExpress Order ID
2. Tracking Number (if available)
3. Product Price (in USD)

Format: orderid|tracking|price
Example: 8675309|LY123456789CN|25.99

Enter 'cancel' to cancel processing.
""",
                parse_mode='HTML'
            )
            bot.register_next_step_handler(msg, process_order_details, order.id, user.telegram_id)
            return
    except Exception as e:
        logger.error(f"Error in order admin decision: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing decision.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '📅 Subscription')
def check_subscription(message):
    """Handle subscription button press with enhanced UI"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id, 
                """
⚠️ <b>REGISTRATION REQUIRED</b>

Please register first to check your subscription status.
You can register by clicking 🔑 Register on the main menu.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu()
            )
            return

        now = datetime.utcnow()
        subscription_active = False
        days_remaining = 0
        subscription_msg = ""
        markup = create_main_menu(is_registered=True)

        # Check subscription status
        if user.subscription_date:
            days_passed = (now - user.subscription_date).days
            days_remaining = 30 - days_passed

            if days_remaining > 0:
                subscription_active = True
                subscription_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>ACTIVE SUBSCRIPTION</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📅 SUBSCRIPTION DETAILS:</b>
• Status: <b>Active</b> 🟢
• Expires in: <b>{days_remaining} days</b>
• Renewal date: <b>{(user.subscription_date + timedelta(days=30)).strftime('%Y-%m-%d')}</b>
• Monthly fee: <b>$1.00</b> (150 birr)

<i>Your subscription will automatically renew when you make your next deposit.</i>

<b>✨ PREMIUM BENEFITS:</b>
• Unlimited order processing
• Priority customer support
• Real-time tracking updates
• Special promotions & discounts
"""
                # If expiring soon, add inline buttons for renewal
                if days_remaining <= 5:
                    renewal_markup = InlineKeyboardMarkup()
                    renewal_markup.add(InlineKeyboardButton("💰 Renew Now", callback_data="deposit_renew"))
                    renewal_markup.add(InlineKeyboardButton("📋 View Benefits", callback_data="sub_benefits"))

                    bot.send_message(
                        chat_id,
                        subscription_msg,
                        parse_mode='HTML',
                        reply_markup=renewal_markup
                    )
                    return
            else:
                # Subscription expired
                days_expired = abs(days_remaining)
                expired_text = "today" if days_expired == 0 else f"{days_expired} days ago"

                subscription_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚫 <b>SUBSCRIPTION EXPIRED</b> 🚫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📅 SUBSCRIPTION DETAILS:</b>
• Status: <b>Expired</b> 🔴
• Expired: <b>{expired_text}</b>
• Monthly fee: <b>$1.00</b> (150 birr)

<i>Please renew your subscription to continue enjoying our premium services.</i>

<b>🔄 HOW TO RENEW:</b>
1. Make a deposit of at least $1
2. Your subscription will automatically renew
3. Enjoy uninterrupted service for another 30 days
"""
                # Add renewal buttons
                renewal_markup = InlineKeyboardMarkup()
                renewal_markup.add(InlineKeyboardButton("💰 Renew Now", callback_data="deposit_renew"))
                renewal_markup.add(InlineKeyboardButton("📋 View Benefits", callback_data="sub_benefits"))

                bot.send_message(
                    chat_id,
                    subscription_msg,
                    parse_mode='HTML',
                    reply_markup=renewal_markup
                )
                return
        else:
            # No subscription yet
            subscription_msg = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ℹ️ <b>NO SUBSCRIPTION</b> ℹ️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📅 SUBSCRIPTION DETAILS:</b>
• Status: <b>Not Active</b> ⚪
• Monthly fee: <b>$1.00</b> (150 birr)

<i>You don't have an active subscription yet. Subscribe now to access premium features!</i>

<b>✨ PREMIUM BENEFITS:</b>
• Unlimited order processing
• Priority customer support
• Real-time tracking updates
• Special promotions & discounts

<b>💡 HOW TO SUBSCRIBE:</b>
Make a deposit of at least $1 to automatically activate your subscription.
"""
            # Add subscription buttons
            subscription_markup = InlineKeyboardMarkup()
            subscription_markup.add(InlineKeyboardButton("💰 Subscribe Now", callback_data="deposit_renew"))
            subscription_markup.add(InlineKeyboardButton("📋 View Benefits", callback_data="sub_benefits"))

            bot.send_message(
                chat_id,
                subscription_msg,
                parse_mode='HTML',
                reply_markup=subscription_markup
            )
            return

        # Send the message with markup only if we didn't return earlier
        bot.send_message(chat_id, subscription_msg, parse_mode='HTML', reply_markup=markup)

    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        logger.error(traceback.format_exc())  # Add traceback for better debugging
        bot.send_message(
            chat_id, 
            "⚠️ <b>Oops!</b> We encountered a temporary glitch. Please try again in a moment. ⚠️",
            parse_mode='HTML'
        )
    finally:
        if session:
            safe_close_session(session)

def process_order_details(message, order_id, user_telegram_id):
    """Process order details provided by admin"""
    session = None
    try:
        if message.text.lower() == 'cancel':
            bot.reply_to(message, "Order processing cancelled.")
            return

        # Parse order details
        try:
            order_details = message.text.strip().split('|')
            if len(order_details) != 3:
                raise ValueError("Invalid format")

            aliexpress_id, tracking, price = order_details
            price = float(price)

        except (ValueError, IndexError):
            bot.reply_to(message, "Invalid format. Please try again with format: orderid|tracking|price")
            return

        session = get_session()
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            bot.reply_to(message, "Order not found.")
            return

        # Get the user to deduct the balance
        user = session.query(User).filter_by(telegram_id=int(user_telegram_id)).first()
        if not user:
            bot.reply_to(message, "User not found.")
            return

        # Store the original balance for notification
        original_balance = user.balance

        # Deduct the order amount from user's balance
        if price > 0:
            user.balance -= price
            logger.info(f"Deducted ${price:.2f} from user {user_telegram_id} balance for order #{order.order_number}")

            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                amount=-price,  # Negative for deduction
                transaction_type="order_payment",
                description=f"Payment for order #{order.order_number}",
                reference=aliexpress_id,
                status="completed"
            )
            session.add(transaction)

        # Update order with the details
        order.order_id = aliexpress_id
        order.tracking_number = tracking if tracking else None
        order.amount = price
        order.status = "Shipped" if tracking else "Processing"
        order.carrier = "Standard AliExpress Shipping"  # Default carrier
        order.updated_at = datetime.utcnow()

        # Commit all changes
        session.commit()

        # Notify user with beautiful formatting
        status_emoji = "🔄"
        status_color = "🔵"
        if order.status == "Shipped":
            status_emoji = "🚚"
            status_color = "🟢"

        tracking_info = ""
        if tracking:
            clean_tracking = tracking.strip().replace(" ", "").replace("+", "%2B")      
            parcels_app_link = f"https://global.cainiao.com/detail.htm?mailNo={clean_tracking}&lang=en"
            tracking_info = f"""
<b>📬 TRACKING INFORMATION:</b>
• Tracking Number: <code>{tracking}</code>
• Carrier: <b>{order.carrier}</b>
• <a href="{parcels_app_link}">📲 Track Package on Cainiao </a> (Real-time updates)
• <a href="https://aliexpress.com/trackOrder.htm">📋 Check on AliExpress</a>
"""

        # Calculate balance in birr
        new_balance = user.balance
        birr_balance = int(new_balance * 160)  # Convert to birr (1 USD = 160 ETB)

        # Add balance info only if price was deducted
        balance_info = ""
        if price > 0:
            balance_info = f"""
<b>💰 ACCOUNT UPDATE:</b>
• Amount charged: <b>${price:.2f}</b> ({int(price * 160)} birr)
• New balance: <b>${new_balance:.2f}</b> ({birr_balance} birr)
"""

        bot.send_message(
            user_telegram_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🎉 <b>ORDER UPDATE</b> 🎉  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your order <b>#{order.order_number}</b> has been {status_emoji} <b>{order.status.lower()}</b>!

<b>📋 ORDER INFORMATION:</b>
• Status: {status_emoji} <b>{order.status}</b> {status_color}
• AliExpress Order ID: <code>{aliexpress_id}</code>
• Amount: <b>${price:.2f}</b>
• Updated: <b>{datetime.utcnow().strftime('%d %b %Y')}</b>
{balance_info}
{tracking_info if tracking else "Your tracking information will be added soon."}

<i>💫 Having issues with your order? Contact our support at @alipay_help_center for assistance 💫</i>
""",
            parse_mode='HTML',
            disable_web_page_preview=True
        )

        bot.reply_to(
            message,
            f"""
✅ Order details added and user notified:
• Order #{order.order_number}
• Order ID: {aliexpress_id}
• Tracking: {tracking if tracking else "None yet"}
• Price: ${price:.2f}
• Status: {order.status}
• User balance: ${original_balance:.2f} → ${user.balance:.2f} (-${price:.2f})
""",
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error processing order details: {e}")
        logger.error(traceback.format_exc())
        bot.reply_to(message, "Error processing order details. Please try again.")
    finally:
        if session:
            safe_close_session(session)

def check_subscription_status():
    """Check subscription status for all users and send reminders"""
    session = None
    try:
        session = get_session()
        users = session.query(User).all()
        now = datetime.utcnow()
        logger.info(f"Checking subscription status for {len(users)} users")

        # Keep track of counts for logging
        auto_renewed = 0
        expiring_notified = 0
        expired_notified = 0

        for user in users:
            try:
                # Skip users without subscription date (never subscribed)
                if not user.subscription_date:
                    continue

                # Calculate days remaining in subscription
                days_passed = (now - user.subscription_date).days
                days_remaining = 30 - days_passed

                # Subscription is current/active
                if days_remaining > 3:
                    # Remove from expired dict if present
                    if user.telegram_id in expired_subscriptions:
                        del expired_subscriptions[user.telegram_id]
                    continue

                # Subscription expiring soon (send notification 3 days before)
                if days_remaining > 0 and days_remaining <= 3:
                    # Only notify once per day by checking if we've already sent
                    notification_key = f"{user.telegram_id}_expiring_{days_remaining}"
                    if notification_key in expired_subscriptions:
                        continue

                    try:
                        # Mark notification as sent for today
                        expired_subscriptions[notification_key] = True

                        # Send expiration warning with renewal button
                        renewal_markup = InlineKeyboardMarkup()
                        renewal_markup.add(InlineKeyboardButton("💰 Renew Now", callback_data="deposit_renew"))

                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ⚠️ <b>SUBSCRIPTION EXPIRING SOON</b> ⚠️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription will expire in <b>{days_remaining} day{'s' if days_remaining > 1 else ''}</b>.

<b>📅 SUBSCRIPTION DETAILS:</b>
• Expiry date: <b>{(user.subscription_date + timedelta(days=30)).strftime('%Y-%m-%d')}</b>
• Monthly fee: <b>$1.00</b> (150 birr)

<b>💰 RENEWAL OPTIONS:</b>
• Auto-renewal: Your subscription will auto-renew if your balance is at least $1.00
• Current balance: <b>${user.balance:.2f}</b>
• Manual renewal: Click 'Renew Now' to add funds

<i>Renew now to maintain uninterrupted access!</i>
""",
                            parse_mode='HTML',
                            reply_markup=renewal_markup
                        )
                        expiring_notified += 1
                        logger.info(f"Sent expiration warning to user {user.telegram_id} ({days_remaining} days left)")
                    except Exception as e:
                        logger.error(f"Error sending expiration warning to user {user.telegram_id}: {e}")

                # Subscription expired - check for auto-renewal from balance
                else:
                    # Try to auto-renew from balance
                    if user.balance >= 1.0:  # User has at least $1
                        try:
                            # Deduct subscription fee
                            previous_balance = user.balance
                            user.balance -= 1.0

                            # Update subscription date
                            user.subscription_date = now
                            session.commit()

                            # Remove from expired dict if present
                            if user.telegram_id in expired_subscriptions:
                                del expired_subscriptions[user.telegram_id]

                            # Send notification
                            bot.send_message(
                                user.telegram_id,
                                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>SUBSCRIPTION AUTO-RENEWED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has been automatically renewed for 30 days.

<b>💰 PAYMENT DETAILS:</b>
• Previous balance: <b>${previous_balance:.2f}</b>
• Renewal fee: <b>$1.00</b>
• New balance: <b>${user.balance:.2f}</b>

<b>📅 NEW EXPIRY DATE:</b>
• {(now + timedelta(days=30)).strftime('%Y-%m-%d')}

<i>Thank you for your continued subscription!</i>
""",
                                parse_mode='HTML'
                            )
                            auto_renewed += 1
                            logger.info(f"✅ Auto-renewed subscription for user {user.telegram_id} from balance ${previous_balance:.2f} -> ${user.balance:.2f}")

                            # Notify admin about renewal
                            for admin_id in ADMIN_IDS:
                                try:
                                    bot.send_message(
                                        admin_id,
                                        f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💲 <b>SUBSCRIPTION AUTO-RENEWED</b>  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Subscription auto-renewed for user:
👤 <b>{user.name}</b> [ID: <code>{user.telegram_id}</code>]
💰 Previous balance: ${previous_balance:.2f}
💰 New balance: ${user.balance:.2f}
""",
                                        parse_mode='HTML'
                                    )
                                except Exception as e:
                                    logger.error(f"Error notifying admin {admin_id} about auto-renewal: {e}")
                        except Exception as e:
                            logger.error(f"Error auto-renewing subscription for user {user.telegram_id}: {e}")

                    # Can't auto-renew, remind user if not already notified
                    elif user.telegram_id not in expired_subscriptions:
                        try:
                            # Mark user as expired
                            expired_subscriptions[user.telegram_id] = True

                            # Create renewal link and notification
                            renewal_markup = InlineKeyboardMarkup()
                            renewal_markup.add(InlineKeyboardButton("💰 Renew Now", callback_data="deposit_renew"))

                            days_expired = abs(days_remaining)
                            bot.send_message(
                                user.telegram_id,
                                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚫 <b>SUBSCRIPTION EXPIRED</b> 🚫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has expired {days_expired} day{'s' if days_expired != 1 else ''} ago.

<b>❗ FEATURE RESTRICTIONS:</b>
• Some features are now locked
• Deposit funds to restore full access

<b>💰 RENEWAL OPTIONS:</b>
• Your balance: <b>${user.balance:.2f}</b>
• Required: <b>$1.00</b> (150 birr)

<i>Click 'Renew Now' to regain immediate access to all features!</i>
""",
                                parse_mode='HTML',
                                reply_markup=renewal_markup
                            )
                            expired_notified += 1
                            logger.info(f"Sent expired notification to user {user.telegram_id} (expired {days_expired} days ago)")
                        except Exception as e:
                            logger.error(f"Error sending expired notification to user {user.telegram_id}: {e}")

            except Exception as e:
                logger.error(f"Error processing subscription for user {user.id}: {e}")

        logger.info(f"Subscription check completed: {auto_renewed} auto-renewed, {expiring_notified} expiring, {expired_notified} expired")

    except Exception as e:
        logger.error(f"Error checking subscription status: {e}")
        logger.error(traceback.format_exc())
    finally:
        if session:
            safe_close_session(session)



def run_subscription_checker():
    """Run the subscription checker periodically"""
    while True:
        try:
            check_subscription_status()
        except Exception as e:
            logger.error(f"Error in subscription checker: {e}")
        # Wait for 24 hours before checking again
        time.sleep(24 * 60 * 60)

# Admin Dashboard Function Handlers
@bot.message_handler(func=lambda msg: msg.text == '🔐 Admin Dashboard')
def admin_dashboard(message):
    """Show admin dashboard with all admin features"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        bot.send_message(
            chat_id,
            "⚠️ You don't have permission to access the admin dashboard.",
            reply_markup=create_main_menu(True, chat_id)
        )
        return

    # Create admin menu
    admin_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    admin_menu.add(
        KeyboardButton('👥 User Management'),
        KeyboardButton('📦 Order Management')
    )
    admin_menu.add(
        KeyboardButton('💰 Deposit Management'),
        KeyboardButton('📊 System Stats')
    )
    admin_menu.add(
        KeyboardButton('📅 Subscription Management'),
        KeyboardButton('⚙️ Bot Settings')
    )
    admin_menu.add(
        KeyboardButton('🔙 Back to Main Menu')
    )

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔐 <b>ADMIN DASHBOARD</b> 🔐  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Welcome to the Admin Dashboard! Select a management option:

<b>Available Admin Features:</b>
• 👥 <b>User Management</b> - View and manage users
• 📦 <b>Order Management</b> - View and manage orders
• 💰 <b>Deposit Management</b> - View and manage deposits
• 📊 <b>System Stats</b> - View system statistics
• 📅 <b>Subscription Management</b> - Manage user subscriptions
• ⚙️ <b>Bot Settings</b> - Configure bot settings

<i>Select any option to continue or go back to the main menu.</i>
""",
        parse_mode='HTML',
        reply_markup=admin_menu
    )

@bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Main Menu')
def back_to_main_menu(message):
    """Return to main menu from admin dashboard"""
    chat_id = message.chat.id
    session = None

    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        is_registered = user is not None

        bot.send_message(
            chat_id,
            "🏠 Returning to main menu...",
            reply_markup=create_main_menu(is_registered, chat_id)
        )
    except Exception as e:
        logger.error(f"Error returning to main menu: {e}")
        bot.send_message(
            chat_id,
            "🏠 Returning to main menu...",
            reply_markup=create_main_menu(True, chat_id)
        )
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '👥 User Management')
def user_management(message):
    """Show user management options"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    # Create user management menu
    user_mgmt_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    user_mgmt_menu.add(
        KeyboardButton('📋 List All Users'),
        KeyboardButton('🔍 Find User')
    )
    user_mgmt_menu.add(
        KeyboardButton('➕ Add User'),
        KeyboardButton('🚫 Block User')
    )
    user_mgmt_menu.add(
        KeyboardButton('✅ Pending Approvals'),
        KeyboardButton('🔙 Back to Admin')
    )

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👥 <b>USER MANAGEMENT</b> 👥  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Manage all user accounts from this panel.

<b>Available Actions:</b>
• 📋 <b>List All Users</b> - View all registered users
• 🔍 <b>Find User</b> - Search for a specific user
• ➕ <b>Add User</b> - Manually add a new user
• 🚫 <b>Block User</b> - Block a user from using the bot
• ✅ <b>Pending Approvals</b> - View pending registration approvals

<i>Select an action or go back to the admin dashboard.</i>
""",
        parse_mode='HTML',
        reply_markup=user_mgmt_menu
    )

@bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Admin')
def back_to_admin(message):
    """Return to admin dashboard"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    admin_dashboard(message)

@bot.message_handler(func=lambda msg: msg.text == '📋 List All Users')
def list_all_users(message):
    """List all registered users with pagination"""
    chat_id = message.chat.id
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        session = get_session()
        # Get total users count for pagination
        total_users = session.query(User).count()

        if total_users == 0:
            bot.send_message(
                chat_id,
                "No users are registered in the system yet.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Set up pagination (first page)
        page = 1
        per_page = 10
        offset = (page - 1) * per_page

        # Get users for the current page
        users = session.query(User).order_by(User.created_at.desc()).limit(per_page).offset(offset).all()

        # Format user list with emojis and nice formatting
        users_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>USER LIST</b> (Page {page})  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Total Registered Users:</b> {total_users}

"""

        for i, user in enumerate(users, 1):
            # Format subscription status
            subscription_status = "❌ Inactive"
            if user.subscription_date:
                days_passed = (datetime.utcnow() - user.subscription_date).days
                if days_passed < 30:
                    subscription_status = f"✅ Active ({30 - days_passed} days left)"

            # Format balance
            balance = f"${user.balance:.2f}" if user.balance is not None else "$0.00"

            # Format date
            join_date = user.created_at.strftime("%Y-%m-%d")

            users_text += f"""
<b>{offset + i}. {user.name}</b> [ID: <code>{user.telegram_id}</code>]
📱 Phone: <code>{user.phone}</code>
💰 Balance: <b>{balance}</b>
📅 Subscription: {subscription_status}
🗓️ Joined: {join_date}
"""

        # Add pagination controls if needed
        if total_users > per_page:
            markup = InlineKeyboardMarkup()

            # Only add Next button on first page
            if page == 1:
                markup.add(InlineKeyboardButton("➡️ Next Page", callback_data=f"users_page_{page+1}"))
            # Add navigation buttons for middle pages
            elif page * per_page < total_users:
                markup.add(
                    InlineKeyboardButton("⬅️ Previous", callback_data=f"users_page_{page-1}"),
                    InlineKeyboardButton("➡️ Next", callback_data=f"users_page_{page+1}")
                )
            # Only add Previous button on last page
            else:
                markup.add(InlineKeyboardButton("⬅️ Previous Page", callback_data=f"users_page_{page-1}"))

            users_text += "\n\n<i>Use the buttons below to navigate between pages.</i>"

            bot.send_message(
                chat_id,
                users_text,
                parse_mode='HTML',
                reply_markup=markup
            )
        else:
            bot.send_message(
                chat_id,
                users_text,
                parse_mode='HTML'
            )

    except Exception as e:
        logger.error(f"Error listing users: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error listing users. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith('users_page_'))
def handle_users_pagination(call):
    """Handle user list pagination"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        bot.answer_callback_query(call.id, "You don't have permission to view this data")
        return

    try:
        # Extract page number from callback data
        page = int(call.data.split('_')[-1])
        per_page = 10
        offset = (page - 1) * per_page

        session = get_session()
        total_users = session.query(User).count()

        # Get users for the requested page
        users = session.query(User).order_by(User.created_at.desc()).limit(per_page).offset(offset).all()

        # Format user list with emojis and nice formatting
        users_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>USER LIST</b> (Page {page})  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Total Registered Users:</b> {total_users}

"""

        for i, user in enumerate(users, 1):
            # Format subscription status
            subscription_status = "❌ Inactive"
            if user.subscription_date:
                days_passed = (datetime.utcnow() - user.subscription_date).days
                if days_passed < 30:
                    subscription_status = f"✅ Active ({30 - days_passed} days left)"

            # Format balance
            balance = f"${user.balance:.2f}" if user.balance is not None else "$0.00"

            # Format date
            join_date = user.created_at.strftime("%Y-%m-%d")

            users_text += f"""
<b>{offset + i}. {user.name}</b> [ID: <code>{user.telegram_id}</code>]
📱 Phone: <code>{user.phone}</code>
💰 Balance: <b>{balance}</b>
📅 Subscription: {subscription_status}
🗓️ Joined: {join_date}
"""

        # Create pagination markup
        markup = InlineKeyboardMarkup()

        # First page - only Next button
        if page == 1 and total_users > per_page:
            markup.add(InlineKeyboardButton("➡️ Next Page", callback_data=f"users_page_{page+1}"))
        # Last page - only Previous button
        elif page * per_page >= total_users:
            markup.add(InlineKeyboardButton("⬅️ Previous Page", callback_data=f"users_page_{page-1}"))
        # Middle pages - both Previous and Next buttons
        else:
            markup.add(
                InlineKeyboardButton("⬅️ Previous", callback_data=f"users_page_{page-1}"),
                InlineKeyboardButton("➡️ Next", callback_data=f"users_page_{page+1}")
            )

        users_text += "\n\n<i>Use the buttons below to navigate between pages.</i>"

        # Update the message with the new page
        bot.edit_message_text(
            users_text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='HTML',
            reply_markup=markup
        )

        # Acknowledge the callback
        bot.answer_callback_query(call.id, f"Showing page {page}")

    except Exception as e:
        logger.error(f"Error in users pagination: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error loading users")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '🔍 Find User')
def find_user_prompt(message):
    """Prompt admin to search for a user"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    # Update user state to wait for search query
    user_states[chat_id] = 'waiting_for_user_search'

    # Create a cancel button
    cancel_markup = ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_markup.add(KeyboardButton('🔙 Back to Admin'))

    bot.send_message(
        chat_id,
        """
🔍 <b>FIND USER</b>

Please enter any of the following to search for a user:
• Telegram ID
• Name (full or partial)
• Phone number (full or partial)

<i>Or click '🔙 Back to Admin' to cancel.</i>
""",
        parse_mode='HTML',
        reply_markup=cancel_markup
    )

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_user_search')
def search_user(message):
    """Search for a user based on input"""
    chat_id = message.chat.id
    search_query = message.text.strip()
    session = None

    # Check if user canceled the search
    if search_query == '🔙 Back to Admin':
        del user_states[chat_id]
        back_to_admin(message)
        return

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        session = get_session()
        users = []

        # Try to parse as Telegram ID (int)
        try:
            telegram_id = int(search_query)
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if user:
                users = [user]
        except ValueError:
            # Not a Telegram ID, search by name or phone
            users = session.query(User).filter(
                (User.name.ilike(f'%{search_query}%')) |
                (User.phone.ilike(f'%{search_query}%'))
            ).all()

        # Clear the user state
        if chat_id in user_states:
            del user_states[chat_id]

        if not users:
            bot.send_message(
                chat_id,
                f"❌ No users found matching '{search_query}'",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Display the search results
        results_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>SEARCH RESULTS</b>  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Found <b>{len(users)}</b> user(s) matching '{search_query}':

"""

        for i, user in enumerate(users, 1):
            # Format subscription status
            subscription_status = "❌ Inactive"
            if user.subscription_date:
                days_passed = (datetime.utcnow() - user.subscription_date).days
                if days_passed < 30:
                    subscription_status = f"✅ Active ({30 - days_passed} days left)"

            # Format balance
            balance = f"${user.balance:.2f}" if user.balance is not None else "$0.00"

            # Format date
            join_date = user.created_at.strftime("%Y-%m-%d")

            # Add inline keyboard for each user for detailed actions
            user_markup = InlineKeyboardMarkup()
            user_markup.add(InlineKeyboardButton(f"👤 Manage User #{i}", callback_data=f"manage_user_{user.telegram_id}"))

            user_text = f"""
<b>{i}. {user.name}</b> [ID: <code>{user.telegram_id}</code>]
📱 Phone: <code>{user.phone}</code>
🏠 Address: {user.address}
💰 Balance: <b>{balance}</b>
📅 Subscription: {subscription_status}
🗓️ Joined: {join_date}
"""

            # For first result, append to results text. For subsequent results, send as separate messages
            if i == 1:
                results_text += user_text
                bot.send_message(
                    chat_id,
                    results_text,
                    parse_mode='HTML',
                    reply_markup=user_markup
                )
            else:
                bot.send_message(
                    chat_id,
                    user_text,
                    parse_mode='HTML',
                    reply_markup=user_markup
                )

    except Exception as e:
        logger.error(f"Error searching users: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error searching users. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_user_'))
def handle_manage_user(call):
    """Handle user management options for a specific user"""
    chat_id = call.message.chat.id
    user_id = int(call.data.split('_')[-1])
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        bot.answer_callback_query(call.id, "You don't have permission to manage users")
        return

    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=user_id).first()

        if not user:
            bot.answer_callback_query(call.id, "User not found")
            return

        # Create user management markup
        user_markup = InlineKeyboardMarkup(row_width=2)
        user_markup.add(
            InlineKeyboardButton("💰 Edit Balance", callback_data=f"edit_balance_{user.telegram_id}"),
            InlineKeyboardButton("📅 Update Subscription", callback_data=f"update_sub_{user.telegram_id}")
        )
        user_markup.add(
            InlineKeyboardButton("📋 View Orders", callback_data=f"view_orders_{user.telegram_id}"),
            InlineKeyboardButton("💬 Send Message", callback_data=f"send_msg_{user.telegram_id}")
        )
        user_markup.add(
            InlineKeyboardButton("🚫 Block User", callback_data=f"block_user_{user.telegram_id}")
        )

        # Format subscription status
        subscription_status = "❌ Inactive"
        if user.subscription_date:
            days_passed = (datetime.utcnow() - user.subscription_date).days
            if days_passed < 30:
                subscription_status = f"✅ Active ({30 - days_passed} days left)"

        # Get user stats
        order_count = session.query(Order).filter_by(user_id=user.id).count()
        pending_deposits = session.query(PendingDeposit).filter_by(user_id=user.id, status='Processing').count()

        # Send user details message
        bot.send_message(
            chat_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👤 <b>USER MANAGEMENT</b>  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>User:</b> {user.name}
<b>Telegram ID:</b> <code>{user.telegram_id}</code>
<b>Phone:</b> <code>{user.phone}</code>
<b>Address:</b> {user.address}

<b>💰 FINANCIAL INFO:</b>
• Balance: <b>${user.balance:.2f}</b>
• Orders: {order_count}
• Pending Deposits: {pending_deposits}

<b>📅 SUBSCRIPTION:</b>
• Status: {subscription_status}
• Start Date: {user.subscription_date.strftime('%Y-%m-%d') if user.subscription_date else 'N/A'}

<b>📊 ACTIVITY:</b>
• Joined: {user.created_at.strftime('%Y-%m-%d')}
• Last Updated: {user.updated_at.strftime('%Y-%m-%d')}

<i>Select an action below to manage this user.</i>
""",
            parse_mode='HTML',
            reply_markup=user_markup
        )

        # Acknowledge the callback
        bot.answer_callback_query(call.id, f"Managing {user.name}")

    except Exception as e:
        logger.error(f"Error managing user: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error loading user details")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '📦 Order Management')
def order_management(message):
    """Show order management options"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    # Create order management menu
    order_mgmt_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    order_mgmt_menu.add(
        KeyboardButton('📋 List All Orders'),
        KeyboardButton('🔍 Find Order')
    )
    order_mgmt_menu.add(
        KeyboardButton('⏳ Pending Orders'),
        KeyboardButton('🚚 Shipping Orders')
    )
    order_mgmt_menu.add(
        KeyboardButton('✅ Completed Orders'),
        KeyboardButton('🔙 Back to Admin')
    )

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📦 <b>ORDER MANAGEMENT</b> 📦  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Manage all customer orders from this panel.

<b>Available Actions:</b>
• 📋 <b>List All Orders</b> - View all orders in the system
• 🔍 <b>Find Order</b> - Search for a specific order
• ⏳ <b>Pending Orders</b> - View orders awaiting processing
• 🚚 <b>Shipping Orders</b> - View orders in transit
• ✅ <b>Completed Orders</b> - View delivered orders

<i>Select an action or go back to the admin dashboard.</i>
""",
        parse_mode='HTML',
        reply_markup=order_mgmt_menu
    )

@bot.message_handler(func=lambda msg: msg.text == '📋 List All Orders')
def list_all_orders(message):
    """List all orders with pagination"""
    chat_id = message.chat.id
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        session = get_session()
        # Get total orders count for pagination
        total_orders = session.query(Order).count()

        if total_orders == 0:
            bot.send_message(
                chat_id,
                "No orders have been placed in the system yet.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Set up pagination (first page)
        page = 1
        per_page = 5
        offset = (page - 1) * per_page

        # Get orders for the current page with user info
        orders = session.query(Order, User).join(User).order_by(Order.created_at.desc()).limit(per_page).offset(offset).all()

        # Format order list with emojis and nice formatting
        orders_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>ORDER LIST</b> (Page {page})  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Total Orders:</b> {total_orders}

"""

        for i, (order, user) in enumerate(orders, 1):
            # Format status with emoji
            status_emoji = "⏳"
            if order.status == "Shipping":
                status_emoji = "🚚"
            elif order.status == "Completed":
                status_emoji = "✅"

            # Format date
            order_date = order.created_at.strftime("%Y-%m-%d")

            # Truncate product link to avoid message too long
            product_link = order.product_link
            if len(product_link) > 30:
                product_link = product_link[:27] + "..."

            orders_text += f"""
<b>{offset + i}. Order #{order.order_number}</b> - {status_emoji} {order.status}
👤 Customer: <b>{user.name}</b> [ID: <code>{user.telegram_id}</code>]
🛍️ Product: <i>{product_link}</i>
💰 Amount: <b>${order.amount:.2f}</b>
📅 Date: {order_date}
"""
            if order.order_id:
                orders_text += f"🆔 AliExpress ID: <code>{order.order_id}</code>\n"
            if order.tracking_number:
                orders_text += f"📦 Tracking: <code>{order.tracking_number}</code>\n"

        # Add pagination controls if needed
        if total_orders > per_page:
            markup = InlineKeyboardMarkup()

            # Only add Next button on first page
            if page == 1:
                markup.add(InlineKeyboardButton("➡️ Next Page", callback_data=f"orders_page_{page+1}"))
            # Add navigation buttons for middle pages
            elif page * per_page < total_orders:
                markup.add(
                    InlineKeyboardButton("⬅️ Previous", callback_data=f"orders_page_{page-1}"),
                    InlineKeyboardButton("➡️ Next", callback_data=f"orders_page_{page+1}")
                )
            # Only add Previous button on last page
            else:
                markup.add(InlineKeyboardButton("⬅️ Previous Page", callback_data=f"orders_page_{page-1}"))

            orders_text += "\n\n<i>Use the buttons below to navigate between pages.</i>"

            bot.send_message(
                chat_id,
                orders_text,
                parse_mode='HTML',
                reply_markup=markup
            )
        else:
            bot.send_message(
                chat_id,
                orders_text,
                parse_mode='HTML'
            )

    except Exception as e:
        logger.error(f"Error listing orders: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error listing orders. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith('orders_page_'))
def handle_orders_pagination(call):
    """Handle order list pagination"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        bot.answer_callback_query(call.id, "You don't have permission to view this data")
        return

    try:
        # Extract page number from callback data
        page = int(call.data.split('_')[-1])
        per_page = 5
        offset = (page - 1) * per_page

        session = get_session()
        total_orders = session.query(Order).count()

        # Get orders for the requested page
        orders = session.query(Order, User).join(User).order_by(Order.created_at.desc()).limit(per_page).offset(offset).all()

        # Format order list with emojis and nice formatting
        orders_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>ORDER LIST</b> (Page {page})  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Total Orders:</b> {total_orders}

"""

        for i, (order, user) in enumerate(orders, 1):
            # Format status with emoji
            status_emoji = "⏳"
            if order.status == "Shipping":
                status_emoji = "🚚"
            elif order.status == "Completed":
                status_emoji = "✅"

            # Format date
            order_date = order.created_at.strftime("%Y-%m-%d")

            # Truncate product link to avoid message too long
            product_link = order.product_link
            if len(product_link) > 30:
                product_link = product_link[:27] + "..."

            orders_text += f"""
<b>{offset + i}. Order #{order.order_number}</b> - {status_emoji} {order.status}
👤 Customer: <b>{user.name}</b> [ID: <code>{user.telegram_id}</code>]
🛍️ Product: <i>{product_link}</i>
💰 Amount: <b>${order.amount:.2f}</b>
📅 Date: {order_date}
"""
            if order.order_id:
                orders_text += f"🆔 AliExpress ID: <code>{order.order_id}</code>\n"
            if order.tracking_number:
                orders_text += f"📦 Tracking: <code>{order.tracking_number}</code>\n"

        # Create pagination markup
        markup = InlineKeyboardMarkup()

        # First page - only Next button
        if page == 1 and total_orders > per_page:
            markup.add(InlineKeyboardButton("➡️ Next Page", callback_data=f"orders_page_{page+1}"))
        # Last page - only Previous button
        elif page * per_page >= total_orders:
            markup.add(InlineKeyboardButton("⬅️ Previous Page", callback_data=f"orders_page_{page-1}"))
        # Middle pages - both Previous and Next buttons
        else:
            markup.add(
                InlineKeyboardButton("⬅️ Previous", callback_data=f"orders_page_{page-1}"),
                InlineKeyboardButton("➡️ Next", callback_data=f"orders_page_{page+1}")
            )

        orders_text += "\n\n<i>Use the buttons below to navigate between pages.</i>"

        # Update the message with the new page
        bot.edit_message_text(
            orders_text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='HTML',
            reply_markup=markup
        )

        # Acknowledge the callback
        bot.answer_callback_query(call.id, f"Showing page {page}")

    except Exception as e:
        logger.error(f"Error in orders pagination: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error loading orders")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '💰 Deposit Management')
def deposit_management(message):
    """Show deposit management options"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    # Create deposit management menu
    deposit_mgmt_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    deposit_mgmt_menu.add(
        KeyboardButton('📋 Pending Deposits'),
        KeyboardButton('🔍 Find Deposit')
    )
    deposit_mgmt_menu.add(
        KeyboardButton('📊 Deposit Summary'),
        KeyboardButton('➕ Add Balance')
    )
    deposit_mgmt_menu.add(
        KeyboardButton('🔙 Back to Admin')
    )

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>DEPOSIT MANAGEMENT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Manage user deposits and balance from this panel.

<b>Available Actions:</b>
• 📋 <b>Pending Deposits</b> - View deposits awaiting approval
• 🔍 <b>Find Deposit</b> - Search for a specific deposit
• 📊 <b>Deposit Summary</b> - View deposit statistics
• ➕ <b>Add Balance</b> - Manually add balance to a user

<i>Select an action or go back to the admin dashboard.</i>
""",
        parse_mode='HTML',
        reply_markup=deposit_mgmt_menu
    )

@bot.message_handler(func=lambda msg: msg.text == '📋 Pending Deposits')
def list_pending_deposits(message):
    """List pending deposits for approval"""
    chat_id = message.chat.id
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        session = get_session()
        # Get all pending deposits with user info (exclude auto-approved ones)
        pending_deposits = session.query(PendingDeposit, User).join(User).filter(
            PendingDeposit.status == 'Processing'
        ).order_by(PendingDeposit.created_at.desc()).all()

        # Get auto-approved deposits count for the admin
        auto_approved_count = session.query(PendingDeposit).filter(
            PendingDeposit.status == 'Auto-Approved'
        ).count()

        if not pending_deposits:
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>DEPOSIT MANAGEMENT</b>  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

✅ <b>No manual approvals needed!</b>

All deposits have been processed. There are no deposits waiting for manual approval.

<b>{auto_approved_count}</b> deposits have been automatically approved by the system.

<i>✅ Online payments through Chapa are now fully automated and require no admin approval!</i>
<i>Only manual deposits (with screenshots) require admin review.</i>
""",
                parse_mode='HTML',
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Send introduction message with auto-approved count
        bot.send_message(
            chat_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>DEPOSIT MANAGEMENT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Found <b>{len(pending_deposits)}</b> deposits pending manual approval.
<b>{auto_approved_count}</b> deposits have been automatically approved by the system.

<i>✅ Online payments through Chapa are now automatically verified and approved!</i>
<i>Manual deposits (with screenshots) still require admin approval.</i>

<i>Each pending deposit will be shown below with approval options.</i>
""",
            parse_mode='HTML'
        )

        # Send each pending deposit as a separate message with approve/reject buttons
        for deposit, user in pending_deposits:
            # Create inline keyboard for approval
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_deposit_{deposit.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_deposit_{deposit.id}")
            )

            # Format deposit message
            deposit_date = deposit.created_at.strftime("%Y-%m-%d %H:%M")

            deposit_msg = f"""
<b>Deposit #{deposit.id}</b>

👤 <b>User:</b> {user.name} [ID: <code>{user.telegram_id}</code>]
💰 <b>Amount:</b> ${deposit.amount:.2f}
⏰ <b>Requested:</b> {deposit_date}

<i>Use the buttons below to approve or reject this deposit.</i>
"""

            bot.send_message(
                chat_id,
                deposit_msg,
                parse_mode='HTML',
                reply_markup=markup
            )

    except Exception as e:
        logger.error(f"Error listing pending deposits: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error listing pending deposits. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

# This handler has been replaced with the improved version at line 1309
# Left this comment for code history tracking purposes

        session = get_session()

        # Get deposit and user
        deposit_info = session.query(PendingDeposit, User).join(User).filter(
            PendingDeposit.id == deposit_id
        ).first()

        if not deposit_info:
            bot.answer_callback_query(call.id, "Deposit not found or already processed")
            bot.edit_message_text(
                "This deposit has already been processed or was not found.",
                chat_id=chat_id,
                message_id=message_id
            )
            return

        deposit, user = deposit_info

        if action == 'approve':
            # Update user balance
            user.balance += deposit.amount

            # Update deposit status
            deposit.status = 'Approved'

            session.commit()

            # Send notification to user
            bot.send_message(
                user.telegram_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your deposit of <b>${deposit.amount:.2f}</b> has been approved!

<b>New Balance:</b> ${user.balance:.2f}

<i>Thank you for using AliPay_ETH!</i>
""",
                parse_mode='HTML'
            )

            # Update admin message
            bot.edit_message_text(
                f"""
<b>Deposit #{deposit.id}</b> - ✅ APPROVED

👤 <b>User:</b> {user.name} [ID: <code>{user.telegram_id}</code>]
💰 <b>Amount:</b> ${deposit.amount:.2f}
💳 <b>New Balance:</b> ${user.balance:.2f}
⏰ <b>Approved at:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}

<i>User has been notified of the approval.</i>
""",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )

            bot.answer_callback_query(call.id, f"Deposit of ${deposit.amount:.2f} approved")

        else:  # Reject
            # Update deposit status
            deposit.status = 'Rejected'
            session.commit()

            # Send notification to user
            bot.send_message(
                user.telegram_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❌ <b>DEPOSIT REJECTED</b> ❌  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your deposit of <b>${deposit.amount:.2f}</b> has been rejected.

<b>Reason:</b> The payment could not be verified.

Please contact customer support for assistance or try again with a clearer payment proof.

<i>For help, please contact @alipay_help_center</i>
""",
                parse_mode='HTML'
            )

            # Update admin message
            bot.edit_message_text(
                f"""
<b>Deposit #{deposit.id}</b> - ❌ REJECTED

👤 <b>User:</b> {user.name} [ID: <code>{user.telegram_id}</code>]
💰 <b>Amount:</b> ${deposit.amount:.2f}
⏰ <b>Rejected at:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}

<i>User has been notified of the rejection.</i>
""",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )

            bot.answer_callback_query(call.id, f"Deposit of ${deposit.amount:.2f} rejected")

    except Exception as e:
        logger.error(f"Error handling deposit approval: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing deposit")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '➕ Add Balance')
def add_balance_prompt(message):
    """Prompt admin to add balance to a user"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    # Update user state to wait for user ID
    user_states[chat_id] = 'waiting_for_balance_user_id'

    # Create a cancel button
    cancel_markup = ReplyKeyboardMarkup(resize_keyboard=True)
    cancel_markup.add(KeyboardButton('🔙 Back to Admin'))

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ➕ <b>ADD USER BALANCE</b> ➕  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Please enter the user's Telegram ID to add balance to their account.

<i>Or click '🔙 Back to Admin' to cancel.</i>
""",
        parse_mode='HTML',
        reply_markup=cancel_markup
    )

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_balance_user_id')
def process_balance_user_id(message):
    """Process the user ID for adding balance"""
    chat_id = message.chat.id
    user_input = message.text.strip()
    session = None

    # Check if user canceled
    if user_input == '🔙 Back to Admin':
        if chat_id in user_states:
            del user_states[chat_id]
        back_to_admin(message)
        return

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        # Try to parse as Telegram ID (int)
        try:
            user_telegram_id = int(user_input)
        except ValueError:
            bot.send_message(
                chat_id,
                "❌ Invalid Telegram ID. Please enter a valid numeric ID.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Check if user exists
        session = get_session()
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()

        if not user:
            bot.send_message(
                chat_id,
                f"❌ No user found with Telegram ID {user_telegram_id}",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Store user info and update state to wait for amount
        user_states[chat_id] = {
            'state': 'waiting_for_balance_amount',
            'user_telegram_id': user_telegram_id,
            'user_name': user.name,
            'current_balance': user.balance
        }

        # Send user info and prompt for amount
        bot.send_message(
            chat_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👤 <b>USER FOUND</b> 👤  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>User:</b> {user.name}
<b>Telegram ID:</b> <code>{user.telegram_id}</code>
<b>Current Balance:</b> ${user.balance:.2f}

Please enter the amount in USD to add to the user's balance.
(e.g., 10 for $10.00)

<i>Or click '🔙 Back to Admin' to cancel.</i>
""",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )

    except Exception as e:
        logger.error(f"Error processing user ID for balance: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error processing user ID. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and isinstance(user_states[msg.chat.id], dict) and user_states[msg.chat.id].get('state') == 'waiting_for_balance_amount')
def process_balance_amount(message):
    """Process the amount to add to user balance"""
    chat_id = message.chat.id
    amount_input = message.text.strip()
    session = None

    # Check if user canceled
    if amount_input == '🔙 Back to Admin':
        if chat_id in user_states:
            del user_states[chat_id]
        back_to_admin(message)
        return

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        # Get user info from state
        user_info = user_states[chat_id]
        user_telegram_id = user_info['user_telegram_id']
        user_name = user_info['user_name']
        current_balance = user_info['current_balance']

        # Try to parse as float
        try:
            amount = float(amount_input)
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except ValueError:
            bot.send_message(
                chat_id,
                "❌ Invalid amount. Please enter a positive number.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Update user balance
        session = get_session()
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()

        if not user:
            bot.send_message(
                chat_id,
                "❌ User not found. They may have been deleted.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
            )
            return

        # Add balance
        new_balance = user.balance + amount
        user.balance = new_balance
        session.commit()

        # Clear user state
        if chat_id in user_states:
            del user_states[chat_id]

        # Notify admin of success
        bot.send_message(
            chat_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>BALANCE ADDED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>User:</b> {user_name}
<b>Telegram ID:</b> <code>{user_telegram_id}</code>
<b>Amount Added:</b> ${amount:.2f}
<b>Previous Balance:</b> ${current_balance:.2f}
<b>New Balance:</b> ${new_balance:.2f}

<i>The user has been notified of the balance update.</i>
""",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )

        # Notify user of balance update
        bot.send_message(
            user_telegram_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>BALANCE UPDATED</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Amount Added:</b> ${amount:.2f}
<b>New Balance:</b> ${new_balance:.2f}

Your account balance has been updated by the administrator.

<i>Thank you for using AliPay_ETH!</i>
""",
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error adding balance: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error adding balance. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '📅 Subscription Management')
def subscription_management(message):
    """Show subscription management options"""
    chat_id = message.chat.id

    # Check if user is admin
    if not is_admin(chat_id):
        return

    # Create subscription management menu
    subscription_mgmt_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    subscription_mgmt_menu.add(
        KeyboardButton('📋 List Subscriptions'),
        KeyboardButton('🔍 Find Subscription')
    )
    subscription_mgmt_menu.add(
        KeyboardButton('⏰ Expiring Soon'),
        KeyboardButton('➕ Extend Subscription')
    )
    subscription_mgmt_menu.add(
        KeyboardButton('🔙 Back to Admin')
    )

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📅 <b>SUBSCRIPTION MANAGEMENT</b> 📅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Manage user subscriptions from this panel.

<b>Available Actions:</b>
• 📋 <b>List Subscriptions</b> - View all active subscriptions
• 🔍 <b>Find Subscription</b> - Search for a user's subscription
• ⏰ <b>Expiring Soon</b> - View subscriptions expiring soon
• ➕ <b>Extend Subscription</b> - Manually extend a subscription

<i>Select an action or go back to the admin dashboard.</i>
""",
        parse_mode='HTML',
        reply_markup=subscription_mgmt_menu
    )

@bot.message_handler(func=lambda msg: msg.text == '📊 System Stats')
def system_stats(message):
    """Show system statistics"""
    chat_id = message.chat.id
    session = None

    # Check if user is admin
    if not is_admin(chat_id):
        return

    try:
        session = get_session()

        # Gather statistics
        total_users = session.query(User).count()

        # Active subscriptions (less than 30 days since subscription date)
        active_subs_query = session.query(User).filter(
            User.subscription_date.isnot(None),
            (datetime.utcnow() - User.subscription_date) < timedelta(days=30)
        )
        active_subscriptions = active_subs_query.count()

        # Orders statistics
        total_orders = session.query(Order).count()
        processing_orders = session.query(Order).filter_by(status='Processing').count()
        completed_orders = session.query(Order).filter_by(status='Completed').count()
        shipped_orders = session.query(Order).filter_by(status='Shipped').count()

        # Deposit statistics
        pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').count()

        # Financial statistics
        total_balance = session.query(func.sum(User.balance)).scalar() or 0

        # Recent activity
        recent_users = session.query(User).order_by(User.created_at.desc()).limit(5).all()
        recent_orders = session.query(Order).order_by(Order.created_at.desc()).limit(5).all()

        # Format the stats message
        stats_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>SYSTEM STATISTICS</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📆 DATE:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<b>👥 USER STATISTICS:</b>
• Total Users: {total_users}
• Active Subscriptions: {active_subscriptions}
• Subscription Rate: {int(active_subscriptions/total_users*100) if total_users > 0 else 0}%

<b>📦 ORDER STATISTICS:</b>
• Total Orders: {total_orders}
• Processing: {processing_orders}
• Shipped: {shipped_orders}
• Completed: {completed_orders}

<b>💰 FINANCIAL STATISTICS:</b>
• Total User Balance: ${total_balance:.2f}
• Pending Deposits: {pending_deposits}

<b>🔄 RECENT ACTIVITY:</b>
"""

        # Add recent users
        stats_message += "\n<b>New Users:</b>"
        for user in recent_users:
            stats_message += f"\n• {user.name} ({user.created_at.strftime('%Y-%m-%d')})"

        # Add recent orders
        stats_message += "\n\n<b>Recent Orders:</b>"
        for order in recent_orders:
            stats_message += f"\n• Order #{order.order_number} - {order.status} ({order.created_at.strftime('%Y-%m-%d')})"

        bot.send_message(
            chat_id,
            stats_message,
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error generating system stats: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ Error generating system statistics. Please try again later.",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(KeyboardButton('🔙 Back to Admin'))
        )
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '❓ Help Center')
def help_center(message):
    """Handle Help Center button with all necessary information"""
    chat_id = message.chat.id

    # Create help center inline buttons
    help_markup = InlineKeyboardMarkup(row_width=1)
    help_markup.add(
        InlineKeyboardButton("📝 How to Register", callback_data="help_register"),
        InlineKeyboardButton("💰 How to Deposit", callback_data="help_deposit"),
        InlineKeyboardButton("🛍️ How to Order", callback_data="help_order"),
        InlineKeyboardButton("🔍 How to Track Orders", callback_data="help_track"),
        InlineKeyboardButton("💬 Contact Support", url="https://t.me/alipay_help_center")
    )

    bot.send_message(
        chat_id,
        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❓ <b>HELP CENTER</b> ❓  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Welcome to AliPay_ETH Help Center!</b>

How can we assist you today? Select a topic below to get detailed information and step-by-step guides.

<b>📋 AVAILABLE HELP TOPICS:</b>
• Registration Process
• Deposit Methods
• Ordering from AliExpress
• Tracking Your Orders
• Subscription Benefits

<i>If you need direct assistance, click 'Contact Support' to chat with our team.</i>

<b>💡 TIP:</b> Our team is available 7 days a week to help you with any questions!
""",
        parse_mode='HTML',
        reply_markup=help_markup
    )

# Skip tutorial functionality has been removed

@bot.callback_query_handler(func=lambda call: call.data.startswith('help_'))
def handle_help_buttons(call):
    """Handle help center button callbacks"""
    chat_id = call.message.chat.id
    help_topic = call.data.split('_')[1]

    # Back button for all help responses
    back_markup = InlineKeyboardMarkup()
    back_markup.add(InlineKeyboardButton("◀️ Back to Help Center", callback_data="help_main"))
    back_markup.add(InlineKeyboardButton("💬 Contact Support", url="https://t.me/alipay_help_center"))

    if help_topic == "register":
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📝 <b>HOW TO REGISTER</b> 📝  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Registration Process:</b>

1️⃣ Click <b>🔑 Register</b> on the main menu
2️⃣ Enter your full name when prompted
3️⃣ Provide your complete delivery address
4️⃣ Enter your phone number (format: 09xxxxxxxx)
5️⃣ Pay the registration fee of 350 birr (200 birr one-time + 150 birr first month)

<b>After Registration:</b>
• Your account will be activated immediately
• You'll gain access to all features
• You can start depositing funds and placing orders

<b>💡 TIP:</b> Make sure to provide accurate details for smooth delivery of your orders.
""",
            parse_mode='HTML',
            reply_markup=back_markup
        )

    elif help_topic == "deposit":
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>HOW TO DEPOSIT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Deposit Process:</b>

1️⃣ Click <b>💰 Deposit</b> on the main menu
2️⃣ Select an amount or choose "Customize"
3️⃣ Transfer the exact amount to our payment details
4️⃣ Take a screenshot of your payment confirmation
5️⃣ Send the screenshot to the bot

<b>Payment Methods:</b>
• Commercial Bank of Ethiopia (CBE)
• TeleBirr mobile money

<b>After Deposit:</b>
• Your payment will be verified
• Your balance will be updated automatically
• You can start placing orders immediately

<b>💡 TIP:</b> Remember that a $1 (150 birr) monthly subscription fee is automatically deducted from your first deposit.
""",
            parse_mode='HTML',
            reply_markup=back_markup
        )

    elif help_topic == "order":
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🛍️ <b>HOW TO ORDER</b> 🛍️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Ordering Process:</b>

1️⃣ Browse AliExpress and find your desired product
2️⃣ Copy the complete product URL/link
3️⃣ Click <b>📦 Submit Order</b> on the main menu
4️⃣ Paste the AliExpress link when prompted
5️⃣ Wait for order confirmation from our team

<b>After Ordering:</b>
• Our team will process your order
• You'll receive an order confirmation with details
• Your balance will be deducted once the price is confirmed
• You'll receive tracking information when available

<b>💡 TIP:</b> Make sure you have sufficient balance before placing orders. Check your balance anytime with the 💳 Balance button.
""",
            parse_mode='HTML',
            reply_markup=back_markup
        )

    elif help_topic == "track":
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>HOW TO TRACK ORDERS</b> 🔍  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Tracking Process:</b>

1️⃣ Click <b>🔍 Track Order</b> on the main menu
2️⃣ Enter your order number when prompted
3️⃣ View your order details and current status

<b>Alternatively:</b>
• Click <b>📊 Order Status</b> to see all your orders
• Use the tracking links provided to track on ParcelsApp

<b>Order Statuses:</b>
• <b>Processing</b> - Order received and being processed
• <b>Confirmed</b> - Order placed on AliExpress
• <b>Shipped</b> - Order shipped with tracking available
• <b>Delivered</b> - Order arrived at destination
• <b>Cancelled</b> - Order cancelled

<b>💡 TIP:</b> You'll receive automatic notifications when your order status changes!
""",
            parse_mode='HTML',
            reply_markup=back_markup
        )

    elif help_topic == "main":
        # Return to the main help center menu
        help_markup = InlineKeyboardMarkup(row_width=1)
        help_markup.add(
            InlineKeyboardButton("📝 How to Register", callback_data="help_register"),
            InlineKeyboardButton("💰 How to Deposit", callback_data="help_deposit"),
            InlineKeyboardButton("🛍️ How to Order", callback_data="help_order"),
            InlineKeyboardButton("🔍 How to Track Orders", callback_data="help_track"),
            InlineKeyboardButton("💬 Contact Support", url="https://t.me/alipay_help_center")
        )

        bot.edit_message_text(
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❓ <b>HELP CENTER</b> ❓  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Welcome to AliPay_ETH Help Center!</b>

How can we assist you today? Select a topic below to get detailed information and step-by-step guides.

<b>📋 AVAILABLE HELP TOPICS:</b>
• Registration Process
• Deposit Methods
• Ordering from AliExpress
• Tracking Your Orders
• Subscription Benefits

<i>If you need direct assistance, click 'Contact Support' to chat with our team.</i>

<b>💡 TIP:</b> Our team is available 7 days a week to help you with any questions!
""",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode='HTML',
            reply_markup=help_markup
        )

    # Acknowledge the callback
    bot.answer_callback_query(call.id)

# AI Assistant handlers
@bot.message_handler(commands=['companion'])
def start_companion(message):
    """Start interaction with AI Assistant"""
    chat_id = message.chat.id

    if not COMPANION_ENABLED:
        bot.send_message(chat_id, "AI Assistant is not available.")
        return

    # Set user in companion conversation mode
    companion_conversations[chat_id] = True

    # Initialize the companion if needed
    global digital_companion
    if not digital_companion:
        digital_companion = DigitalCompanion(bot)

    # Send greeting
    digital_companion.send_greeting(chat_id)

    # Show helper info
    bot.send_message(
        chat_id,
        "<i>💡 You can now chat directly with the AI Assistant! Type 'exit' or '/exit' to return to the main menu.</i>",
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda msg: msg.text == '🤖 AI Assistant')
def handle_companion_button(message):
    """Handle the companion button press"""
    chat_id = message.chat.id

    # Add user to the companion conversation state
    companion_conversations[chat_id] = True

    # Show a transitional message
    bot.send_message(
        chat_id,
        "🌟 <b>Connecting to AI Assistant, your shopping companion...</b> 🌟",
        parse_mode='HTML'
    )

    # Start the companion interaction
    start_companion(message)

# Handle ANY message from users who are in an active conversation with the companion
@bot.message_handler(func=lambda msg: msg.chat.id in companion_conversations and companion_conversations.get(msg.chat.id))
def handle_companion_message(message):
    """Handle any messages from users in an active companion conversation"""
    if not COMPANION_ENABLED:
        return

    chat_id = message.chat.id

    # Check for exit commands
    if message.text == '/exit' or message.text == 'exit' or message.text == 'back' or message.text == 'main menu':
        companion_conversations[chat_id] = False

        # Send exit message
        bot.send_message(
            chat_id,
            "🌟 <b>Leaving conversation with AI Assistant...</b>\nReturning to main menu!",
            parse_mode='HTML'
        )

        # Return to main menu
        session = None
        try:
            session = get_session()
            user = session.query(User).filter_by(telegram_id=chat_id).first()
            is_registered = user is not None
            bot.send_message(
                chat_id,
                "How else can I help you today?",
                reply_markup=create_main_menu(is_registered=is_registered, chat_id=chat_id)
            )
        except Exception as e:
            logger.error(f"Error returning to main menu: {e}")
            bot.send_message(chat_id, "Back to main menu", reply_markup=create_main_menu(False, chat_id))
        finally:
            safe_close_session(session)
        return

    # Initialize the companion if needed
    global digital_companion
    if not digital_companion:
        digital_companion = DigitalCompanion(bot)

    # Process the message
    digital_companion.process_message(message)

# Also keep this handler for messages that start with AI or Assistant for users not in active conversation
@bot.message_handler(func=lambda msg: (msg.text and (msg.text.startswith('AI') or msg.text.startswith('Assistant'))) and msg.chat.id not in companion_conversations)
def handle_ai_assistant_greeting(message):
    """Handle greeting messages to AI Assistant when not in active conversation"""
    if not COMPANION_ENABLED:
        return

    chat_id = message.chat.id

    # Add user to companion conversations
    companion_conversations[chat_id] = True

    # Initialize the companion if needed
    global digital_companion
    if not digital_companion:
        digital_companion = DigitalCompanion(bot)

    # Process the message
    digital_companion.process_message(message)

@bot.callback_query_handler(func=lambda call: call.data == "deposit_renew")
def handle_subscription_renewal(call):
    """Handle subscription renewal button clicks"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = None

    # Make sure to answer the callback to clear waiting status
    bot.answer_callback_query(call.id, "Processing subscription renewal...")

    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id, 
                "⚠️ Please register first to renew your subscription.",
                reply_markup=create_main_menu()
            )
            return

        # Generate a unique transaction reference
        import uuid
        tx_ref = f"SUB-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:12]}"

        # Create a pending record in the database
        renewal = PendingDeposit(
            user_id=user.id,
            telegram_id=chat_id,
            amount=1.0,  # $1 for subscription
            tx_ref=tx_ref,
            status="pending",
            for_subscription=True,
            created_at=datetime.utcnow()
        )
        session.add(renewal)
        session.commit()

        # Generate payment link
        from chapa_payment import generate_deposit_payment
        payment_data = {
            "email": user.name.replace(" ", "") + f".{chat_id}@example.com",
            "amount": 150,  # 150 birr
            "first_name": user.name.split()[0] if ' ' in user.name else user.name,
            "last_name": user.name.split()[-1] if ' ' in user.name else "User",
            "tx_ref": tx_ref,
            "callback_url": os.environ.get("CALLBACK_URL", "https://alipayeth.onrender.com/webhook"),
            "return_url": os.environ.get("RETURN_URL", "https://t.me/AliPayEthBot"),
            "currency": "ETB",
            "phone_number": user.phone,
            "customization": {
                "title": "Subscription Renewal",
                "description": "Payment for AliPay ETH subscription renewal"
            }
        }

        # Generate Chapa payment URL
        payment_result = generate_deposit_payment(payment_data, 1.0)  # 1.0 USD = 150 birr

        # Extract checkout URL from result
        checkout_url = payment_result.get('checkout_url') if payment_result else None

        if not checkout_url:
            bot.send_message(
                chat_id,
                "❌ Error generating payment link. Please try again later or contact support.",
                reply_markup=create_main_menu(is_registered=True)
            )
            return

        # Send payment instructions with the payment link
        payment_markup = InlineKeyboardMarkup()
        payment_markup.add(InlineKeyboardButton("💳 Pay Now - 150 birr", url=checkout_url))

        bot.send_message(
            chat_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>SUBSCRIPTION RENEWAL</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

You're about to renew your subscription for:
• Monthly fee: <b>$1.00</b> (150 birr)
• Duration: <b>30 days</b>

<b>Click the Pay Now button below to complete your renewal:</b>
""",
            parse_mode='HTML',
            reply_markup=payment_markup
        )

    except Exception as e:
        logger.error(f"Error processing subscription renewal: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id, 
            "⚠️ An error occurred while processing your subscription renewal. Please try again later.",
            reply_markup=create_main_menu(is_registered=True)
        )
    finally:
        if session:
            safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith('retry_payment_'))
def handle_payment_retry(call):
    """Handle payment retry button for cancelled or failed payments"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = None

    # Make sure to answer the callback to clear waiting status
    bot.answer_callback_query(call.id, "Processing payment retry...")

    try:
        # Extract user ID from callback data
        telegram_id = int(call.data.split('retry_payment_')[1])

        # Verify this is the same user who's clicking their own retry button
        if chat_id != telegram_id:
            bot.edit_message_text(
                "⚠️ This payment retry button is for another user.",
                chat_id=chat_id,
                message_id=message_id
            )
            return

        # Get the pending approval from database
        session = get_session()
        pending = session.query(PendingApproval).filter_by(telegram_id=telegram_id).first()

        if not pending:
            bot.edit_message_text(
                "⚠️ Your registration is no longer pending. Please restart with /start if needed.",
                chat_id=chat_id,
                message_id=message_id
            )
            return

        # Reset failed payment status and generate new payment link
        pending.status = 'Pending'

        # Generate a new payment link with Chapa
        from chapa_payment import generate_registration_payment

        # Create user data dictionary for payment generation
        user_data = {
            'telegram_id': pending.telegram_id,
            'name': pending.name,
            'email': f"user.{pending.telegram_id}@gmail.com",  # Fallback email format
            'phone': pending.phone
        }

        # Generate a new payment link
        payment_result = generate_registration_payment(user_data)

        if not payment_result or 'checkout_url' not in payment_result:
            logger.error(f"Failed to generate payment retry URL for user {telegram_id}")
            bot.edit_message_text(
                "❌ <b>Payment Error</b>\n\nWe couldn't generate a new payment link. Please try again later or contact support.",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            return

        # Extract payment URL and tx_ref from result
        payment_url = payment_result.get('checkout_url')
        tx_ref = payment_result.get('tx_ref')

        # Update the transaction reference
        pending.tx_ref = tx_ref
        session.commit()

        # Send the new payment link
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        payment_markup = InlineKeyboardMarkup()
        payment_markup.add(InlineKeyboardButton("💳 Pay 350 Birr", url=payment_url))

        bot.edit_message_text(
            f"""
<b>🔄 PAYMENT RETRY INITIALIZED</b>

Your previous payment attempt was cancelled. A new payment link has been generated.

<b>Registration Fee:</b>
• One-time Fee: 200 Birr
• First Month Subscription: 150 Birr
• <b>Total: 350 Birr</b>

<i>Click the button below to complete your payment. After successful payment, your registration will be automatically approved.</i>
""",
            chat_id=chat_id,
            message_id=message_id,
            parse_mode='HTML',
            reply_markup=payment_markup
        )

        logger.info(f"Payment retry initialized for user {telegram_id} with new tx_ref: {tx_ref}")

    except Exception as e:
        logger.error(f"Error handling payment retry: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "❌ <b>Error</b>\n\nThere was a problem processing your payment retry. Please try again or contact support.",
            parse_mode='HTML'
        )
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith('companion_'))
def handle_companion_callback(call):
    """Handle companion button callbacks"""
    if not COMPANION_ENABLED:
        return

    try:
        # Initialize the companion if needed
        global digital_companion
        if not digital_companion:
            digital_companion = DigitalCompanion(bot)

        # Handle the callback
        digital_companion.handle_callback(call)
    except Exception as e:
        logger.error(f"Error in companion callback: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing request")

@bot.callback_query_handler(func=lambda call: call.data in ['view_referrals', 'redeem_points', 'referral_help', 'view_badges', 'back_to_reflink'])
def handle_referral_badges_buttons(call):
    """Handle callback actions for referral badges screen"""
    chat_id = call.message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.answer_callback_query(call.id, "You need to register first")
            return

        if call.data == 'view_referrals':
            # Get user's referrals
            from referral_system import get_user_referrals
            referrals = get_user_referrals(user.id)

            if not referrals:
                bot.answer_callback_query(call.id, "You haven't referred anyone yet")
                bot.send_message(
                    chat_id,
                    """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>YOUR REFERRALS</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

You haven't referred anyone yet.

<i>Share your referral code or link with friends to start earning points!</i>
""",
                    parse_mode='HTML'
                )
                return

            # Build referral list
            referral_list = ""
            for i, ref in enumerate(referrals, 1):
                status_emoji = "✅" if ref['status'] == 'completed' else "⏳"
                date = ref['referral_date'].strftime('%Y-%m-%d') if ref['referral_date'] else "Unknown"
                referral_list += f"{i}. {status_emoji} <b>{ref['referred_name']}</b> • <i>{date}</i>\n"

            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>YOUR REFERRALS</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>You've referred {len(referrals)} friends:</b>

{referral_list}

<i>Each successful referral earns you 50 points!</i>
""",
                parse_mode='HTML'
            )

        elif call.data == 'redeem_points':
            # Check referral points
            points = user.referral_points or 0

            if points < 100:
                bot.answer_callback_query(call.id, "You need at least 100 points to redeem")
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>REDEEM POINTS</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Your current points:</b> <code>{points}</code>

You need at least <b>100 points</b> to redeem them for account balance.

<i>Invite more friends to earn points!</i>
""",
                    parse_mode='HTML'
                )
                return

            # Start redemption flow
            user_states[chat_id] = 'waiting_for_redemption_amount'

            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>REDEEM POINTS</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Your current points:</b> <code>{points}</code>
<b>Worth:</b> <code>{points}</code> birr

Enter how many points you want to redeem:
• Minimum: <code>100</code> points
• Maximum: <code>{points}</code> points

<i>1 point = 1 birr in account balance</i>
""",
                parse_mode='HTML'
            )

        elif call.data == 'referral_help':
            bot.answer_callback_query(call.id)

            # Get user's referral code and URL
            from referral_system import get_referral_url
            referral_code = user.referral_code or ""
            referral_url = get_referral_url(referral_code) if referral_code else "Referral code not set"

            # Send referral system explanation
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ℹ️ <b>HOW REFERRALS WORK</b> ℹ️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>🏆 Earn Badges and Points:</b>
• Invite friends using your referral link or code
• Earn <b>50 points</b> for each successful registration
• Collect beautiful badges as you refer more friends
• Redeem points for account balance (1 point = 1 birr)

<b>🎯 How to Refer Friends:</b>
1️⃣ Share your personal referral link:
<code>{referral_url}</code>

2️⃣ Or share your referral code:
<code>{referral_code}</code>

3️⃣ Ask them to enter your code during registration

<b>💎 Badge Achievements:</b>
• 🥉 <b>Beginner Referrer:</b> 1 referral
• 🥈 <b>Rising Referrer:</b> 3 referrals
• 🥇 <b>Champion Referrer:</b> 5 referrals
• 💎 <b>Elite Referrer:</b> 10 referrals
• 👑 <b>Legendary Referrer:</b> 20 referrals

<i>Note: Points are awarded ONLY for successful registrations.</i>
""",
                parse_mode='HTML'
            )

        elif call.data == 'view_badges':
            bot.answer_callback_query(call.id)

            # Display coming soon message
            bot.send_message(
                chat_id,
                """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🏆 <b>REFERRAL BADGES</b> 🏆  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>This feature is coming soon!</b>

Our referral system is currently under development and will be available soon.
You'll be able to invite friends and earn rewards.

<i>Stay tuned for updates!</i>
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True, chat_id=chat_id)
            )
            return

        elif call.data == 'redeem_points':
            # Check referral points
            points = user.referral_points or 0

            # Display coming soon message
            bot.send_message(
                chat_id,
                """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>REDEEM POINTS</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>This feature is coming soon!</b>

Our referral system is currently under development and will be available soon.
You'll be able to redeem your points for account balance.

<i>Stay tuned for updates!</i>
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True, chat_id=chat_id)
            )
            return

        elif call.data == 'view_referrals':
            # Display coming soon message
            bot.send_message(
                chat_id,
                """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>YOUR REFERRALS</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>This feature is coming soon!</b>

Our referral system is currently under development and will be available soon.
You'll be able to invite friends and earn rewards.

<i>Stay tuned for updates!</i>
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True, chat_id=chat_id)
            )
            return

        elif call.data == 'back_to_reflink':
            bot.answer_callback_query(call.id)

            # Return to the referral link view
            try:
                # Get or generate referral code
                referral_code = user.referral_code
                if not referral_code:
                    try:
                        from referral_system import assign_referral_code
                        referral_code = assign_referral_code(user.id)
                        logger.info(f"Generated new referral code {referral_code} for user {chat_id}")
                        # Refresh user to get updated code
                        session.refresh(user)
                        referral_code = user.referral_code
                    except Exception as ref_err:
                        logger.error(f"Error generating referral code: {ref_err}")

                if not referral_code:
                    bot.send_message(
                        chat_id,
                        "Sorry, there was an error generating your referral code. Please try again later.",
                        reply_markup=create_main_menu(is_registered=True)
                    )
                    return

                # Get referral URL
                from referral_system import get_referral_url
                referral_url = get_referral_url(referral_code)

                # Count user's successful referrals
                from sqlalchemy import text
                query = text("""
                SELECT COUNT(*) as count
                FROM referrals
                WHERE referrer_id = :user_id
                """)
                result = session.execute(query, {'user_id': user.id}).fetchone()
                referral_count = result.count if result else 0

                # Get user's current points
                points = user.referral_points or 0

                # Create inline keyboard for sharing
                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                markup = InlineKeyboardMarkup()

                # Direct share buttons for common platforms
                markup.row(
                    InlineKeyboardButton("📱 Share via Telegram", url=f"https://t.me/share/url?url={referral_url}&text=Join%20AliPay%20ETH%20shopping%20service%20and%20we%20both%20get%20rewards!%20Use%20my%20referral%20link:")
                )

                markup.row(
                    InlineKeyboardButton("📊 View My Referrals", callback_data="view_referrals"),
                    InlineKeyboardButton("🏆 View Badges", callback_data="view_badges")
                )

                # Send message with QR code and referral details
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔗 <b>YOUR REFERRAL LINK</b> 🔗  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Share your link and earn rewards!</b>

<b>🔢 Your Referral Code:</b> 
<code>{referral_code}</code>

<b>🔗 Your Referral Link:</b>
<code>{referral_url}</code>

<b>📊 Stats:</b>
• <code>{referral_count}</code> successful referrals
• <code>{points}</code> points earned (worth {points} birr)

<b>💰 How it works:</b>
• Share your link with friends
• When they register, you earn 50 points
• Redeem points for account balance (1 point = 1 birr)

<i>Copy the link above and share it with friends!</i>
""",
                    parse_mode='HTML',
                    reply_markup=markup
                )
            except Exception as ref_err:
                logger.error(f"Error displaying referral link: {ref_err}")
                logger.error(traceback.format_exc())
                bot.send_message(chat_id, "Error displaying referral link. Please try again later.")

    except Exception as e:
        logger.error(f"Error handling referral button: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing request")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_redemption_amount')
def process_redemption_amount(message):
    """Process user's points redemption amount"""
    chat_id = message.chat.id
    session = None
    try:
        # Get the amount to redeem
        amount_text = message.text.strip()

        # Check if the input is a valid number
        try:
            points_to_redeem = int(amount_text)
        except ValueError:
            bot.send_message(
                chat_id,
                """
❌ <b>Invalid Amount</b>

Please enter a valid number of points to redeem.
""",
                parse_mode='HTML'
            )
            return

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id,
                "You need to register first.",
                reply_markup=create_main_menu(is_registered=False)
            )
            del user_states[chat_id]
            return

        # Get user's current points
        points = user.referral_points or 0

        # Validate redemption amount
        if points_to_redeem < 100:
            bot.send_message(
                chat_id,
                """
❌ <b>Amount Too Small</b>

You need to redeem at least 100 points.
Please enter a larger amount.
""",
                parse_mode='HTML'
            )
            return

        if points_to_redeem > points:
            bot.send_message(
                chat_id,
                f"""
❌ <b>Insufficient Points</b>

You only have <code>{points}</code> points.
Please enter a smaller amount.
""",
                parse_mode='HTML'
            )
            return

        # Process redemption
        from referral_system import redeem_points
        success, result = redeem_points(user.id, points_to_redeem)

        if success and result:
            remaining_points = result['remaining_points']
            etb_value = result['etb_value']
            new_balance = result['new_balance']

            # Show success message
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>POINTS REDEEMED!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>🎉 Redemption Successful! 🎉</b>

<b>Points redeemed:</b> <code>{points_to_redeem}</code> points
<b>Value added:</b> <code>{etb_value:.2f}</code> birr

<b>Updated Information:</b>
• Remaining points: <code>{remaining_points}</code>
• New balance: $<code>{new_balance:.2f}</code>

<i>Thank you for participating in our referral program!</i>
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )
        else:
            # Show error message
            bot.send_message(
                chat_id,
                """
❌ <b>Redemption Failed</b>

There was an error processing your points redemption.
Please try again later or contact support.
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )

        # Reset user state
        del user_states[chat_id]

    except Exception as e:
        logger.error(f"Error processing redemption: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
        if chat_id in user_states:
            del user_states[chat_id]
    finally:
        safe_close_session(session)

def main():
    """Main function to start the bot with unlimited request handling capabilities"""
    global digital_companion

    logger.info("🚀 Starting bot with unlimited request handling and smart error recovery...")

    # Initialize the database connection manager
    try:
        from connection_manager import connection_manager
        connection_manager.check_connection()
        logger.info("✅ Connection manager initialized with optimized pool settings")

        # Initialize the database
        init_db()
        logger.info("✅ Database initialized")
    except Exception as db_error:
        logger.error(f"❌ Database initialization error: {db_error}")
        logger.error(traceback.format_exc())
        return False

    # Start the request manager for unlimited request handling
    try:
        # Configure the request manager based on environment
        from request_manager import request_manager
        request_manager.start()
        logger.info("✅ Request manager started with queue-based handling")
    except Exception as req_error:
        logger.error(f"❌ Failed to start request manager: {req_error}")
        logger.error(traceback.format_exc())
        return False

    # Start the bot recovery manager for handling bot interruptions
    try:
        # Initialize and start the recovery manager
        from bot_recovery import recovery_manager
        recovery_manager.start()
        logger.info("✅ Bot recovery manager started with smart state persistence")
    except Exception as recovery_error:
        logger.error(f"❌ Failed to start recovery manager: {recovery_error}")
        logger.error(traceback.format_exc())
        # Don't return False here, as we can continue without recovery

    # Initialize AI Assistant if enabled
    if COMPANION_ENABLED:
        try:
            digital_companion = DigitalCompanion(bot)
            logger.info("✅ AI Assistant initialized with complete knowledge of bot features")
        except Exception as e:
            logger.error(f"Failed to initialize AI Assistant: {e}")
            digital_companion = None

    # Tutorial functionality is now disabled
    logger.info("🚫 Interactive Tutorial functionality has been completely disabled")

    # Delete any existing webhook
    try:
        bot.delete_webhook()
        logger.info("✅ Webhook cleared")
    except Exception as e:
        logger.error(f"Error clearing webhook: {e}")

    # Bot performance optimization settings
    bot.threaded = True  # Enable threaded mode for better concurrent handling

    # Connection pool optimization
    try:
        from telebot.apihelper import ApiTelegramException
        logger.info("Applying telebot connection pool optimization...")
        telebot.apihelper.SESSION_TIME_TO_LIVE = 5 * 60  # 5 minutes session TTL
        telebot.apihelper.RETRY_ON_ERROR = True
        telebot.apihelper.CONNECT_TIMEOUT = 5.0  # Reduce connection timeout
        telebot.apihelper.READ_TIMEOUT = 7.0  # Slightly longer read timeout

        # Set up aggressive retry options for reliability
        telebot.apihelper.MAX_RETRIES = 5  # Retry up to 5 times
        telebot.apihelper.RETRY_TIMEOUT = 3  # Start with 3 seconds between retries

        logger.info("Telebot connection optimizations applied")
    except Exception as optimization_error:
        logger.warning(f"Could not apply all performance optimizations: {optimization_error}")

    # Payment notifications are now handled entirely by the standalone chapa_autopay.py process
    # No need to start a duplicate payment notifier from here
    logger.info("✅ Using standalone chapa_autopay.py for payment processing")
    logger.info("✓ Payment notifications will be handled by the Payment Auto-Approver workflow")

    logger.info("✅ Bot handler setup complete with unlimited concurrent request handling")
    logger.info("✓ The bot can now handle unlimited messages without crashing")
    logger.info("✓ Smart error recovery system will preserve user state during interruptions")

    # Start polling with recovery and enhanced error handling
    while not shutdown_requested:
        try:
            logger.info("Starting polling...")
            # Use smaller interval to be more responsive (0.1 seconds)
            bot.polling(none_stop=True, timeout=30, interval=0.1)  # More responsive polling
        except Exception as e:
            if shutdown_requested:
                break
            logger.error(f"Polling error: {e}")
            logger.error(traceback.format_exc())

            # Check database connection before restarting
            try:
                from connection_manager import connection_manager
                connection_manager.check_connection()
            except Exception as db_check_error:
                logger.error(f"Database connection check failed: {db_check_error}")
                # Try to reset the pool
                try:
                    connection_manager.reset_pool()
                except:
                    pass

            # Slightly longer delay for stability
            logger.info("Restarting in 5 seconds...")
            time.sleep(5)

    # Clean shutdown
    try:
        # Stop the request manager
        request_manager.stop()
        logger.info("✅ Request manager stopped")
    except Exception as stop_error:
        logger.error(f"Error stopping request manager: {stop_error}")

    logger.info("Bot shutdown complete")

if __name__ == "__main__":
    # Start the subscription checker in a separate thread
    subscription_thread = threading.Thread(target=run_subscription_checker)
    subscription_thread.daemon = True
    subscription_thread.start()
    main()

import os
import logging
import sys
import telebot
import time
import traceback
import signal
import threading
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import init_db, get_session, safe_close_session
from models import User, Order, PendingApproval, PendingDeposit
from datetime import datetime

# Add signal handling for graceful shutdown
shutdown_requested = False
bot_instance = None

def signal_handler(sig, frame):
    """Handle termination signals for graceful shutdown"""
    global shutdown_requested, bot_instance
    logger = logging.getLogger(__name__)
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_requested = True
    
    # If bot instance exists, stop polling
    if bot_instance:
        try:
            logger.info("Stopping bot polling...")
            bot_instance.stop_polling()
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
    
    # Exit after a short delay to allow cleanup
    threading.Timer(3.0, sys.exit, args=(0,)).start()

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Get bot token from environment
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_ID = os.environ.get('ADMIN_CHAT_ID')

if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN not found!")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except (ValueError, TypeError):
    logger.warning("⚠️ ADMIN_CHAT_ID is not valid. Admin notifications will be skipped.")
    ADMIN_ID = None

# Initialize bot with large timeout
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
bot_instance = bot  # Store reference for signal handling

# Cache for user data
_user_cache = {}
user_states = {}
registration_data = {}

def create_main_menu(is_registered=False):
    """Create the main menu keyboard based on registration status"""
    menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)

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
            KeyboardButton('👥 Join Community'),
            KeyboardButton('❓ Help Center')
        )
    else:
        menu.add(KeyboardButton('🔑 Register'))
        menu.add(
            KeyboardButton('👥 Join Community'),
            KeyboardButton('❓ Help Center')
        )
    return menu

@bot.message_handler(commands=['start'])
def start_message(message):
    """Handle /start command"""
    chat_id = message.chat.id
    session = None
    try:
        logger.info(f"Received /start from user {chat_id}")
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        is_registered = user is not None

        # Reset user state if any
        if chat_id in user_states:
            del user_states[chat_id]
        if chat_id in registration_data:
            del registration_data[chat_id]

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
        bot.send_message(
            chat_id,
            welcome_msg,
            reply_markup=create_main_menu(is_registered),
            parse_mode='HTML'
        )
        logger.info(f"Sent welcome message to user {chat_id}")
    except Exception as e:
        logger.error(f"❌ Error in start command: {traceback.format_exc()}")
        bot.send_message(chat_id, "Welcome to AliPay_ETH!", reply_markup=create_main_menu())
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
            bot.send_message(chat_id, "You are already registered!", reply_markup=create_main_menu(is_registered=True))
            return

        # Check pending approvals
        pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()
        if pending:
            bot.send_message(chat_id, "Your registration is pending approval. Please wait.", reply_markup=create_main_menu(is_registered=False))
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
    """Process phone and request payment"""
    chat_id = message.chat.id
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
        user_states[chat_id] = 'waiting_for_payment'

        payment_msg = f"""
╔═══《 📝 》═══╗
║ Registration ║
╚═══《 💫 》═══╝

<b>👤 User Details:</b>
┌─────────────────┐
│ 📛 {registration_data[chat_id]['name']}
│ 📱 <code>{registration_data[chat_id]['phone']}</code>
│ 📍 {registration_data[chat_id]['address']}
└─────────────────┘

<b>💰 Registration Fee:</b>
┌─────────────────┐
│ 🇺🇸 <code>$1.00</code> USD
│ 🇪🇹 <code>150</code> ETB
└─────────────────┘

<b>💳 Choose Payment Method:</b>

🏦 <b>Commercial Bank (CBE)</b>
┌─────────────────┐
│ 💠 Account: <code>1000547241316</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

📱 <b>TeleBirr Mobile Money</b>
┌─────────────────┐
│ 💠 Number: <code>0986693062</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

<b>📝 Instructions:</b>
1️⃣ Choose your preferred method above
2️⃣ Send exactly <code>150 ETB</code>
3️⃣ Take a clear screenshot
4️⃣ Send the screenshot below ⬇️
"""
        bot.send_message(chat_id, payment_msg, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Error processing phone: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_payment', content_types=['photo'])
def handle_payment_screenshot(message):
    """Process payment screenshot with maximum reliability"""
    chat_id = message.chat.id
    session = None
    registration_complete = False

    # First, acknowledge receipt immediately to provide user feedback
    try:
        bot.send_chat_action(chat_id, 'typing')
        # Store important data in case of later errors
        if chat_id not in registration_data:
            logger.error(f"Missing registration data for user {chat_id}")
            bot.send_message(chat_id, "Registration data missing. Please restart registration with /start.")
            return
    except Exception as e:
        logger.error(f"Initial acknowledgment error: {e}")

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

        # Check if user already has a pending approval to prevent duplicates
        for db_attempt in range(3):  # Retry DB operations
            try:
                session = get_session()
                existing_pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()

                if existing_pending:
                    logger.info(f"User {chat_id} already has a pending approval")
                    bot.send_message(
                        chat_id,
                        """
╔═════《 ⚠️ 》═════╗
║ ALREADY PENDING ║
╚═════《 ⚠️ 》═════╝

<b>Your registration is already being processed!</b>

Please wait for admin approval. You'll be notified once your account is activated.
""",
                        parse_mode='HTML'
                    )
                    safe_close_session(session)
                    return
                break
            except Exception as db_error:
                logger.error(f"Database check error (attempt {db_attempt+1}): {db_error}")
                safe_close_session(session)
                if db_attempt == 2:  # Last attempt failed
                    raise
                time.sleep(0.5 * (db_attempt + 1))  # Progressive delay

        # Add retries for database operations with transactional safety
        max_retries = 5
        for retry_count in range(max_retries):
            try:
                # Always get a fresh session for each retry
                if session:
                    safe_close_session(session)
                session = get_session()

                # Create new pending approval
                pending = PendingApproval(
                    telegram_id=chat_id,
                    name=registration_data[chat_id]['name'],
                    phone=registration_data[chat_id]['phone'],
                    address=registration_data[chat_id]['address']
                )
                session.add(pending)
                session.commit()
                logger.info(f"Added pending approval for user {chat_id}")
                break
            except Exception as db_error:
                logger.error(f"Database error (attempt {retry_count+1}/{max_retries}): {db_error}")
                logger.error(traceback.format_exc())
                session.rollback()
                if retry_count >= max_retries - 1:
                    raise
                time.sleep(0.5 * (retry_count + 1))  # Progressive delay

        # Admin approval buttons
        admin_markup = InlineKeyboardMarkup()
        admin_markup.row(
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{chat_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{chat_id}")
        )

        # Admin notification
        admin_msg = f"""
╔═══《 🔔 》═══╗
║ New User! ║
╚═══《 💫 》═══╝

<b>👤 User Information:</b>
┌─────────────────┐
│ Name: <b>{registration_data[chat_id]['name']}</b>
│ Address: {registration_data[chat_id]['address']}
│ Phone: <code>{registration_data[chat_id]['phone']}</code>
│ ID: <code>{chat_id}</code>
└─────────────────┘

<b>💳 Registration Fee:</b> $1 (150 ETB)
📸 Payment screenshot attached below
⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<b>Please verify the payment and approve or reject.</b>
"""
        # Send admin notification with retry
        admin_notify_success = False
        if ADMIN_ID:
            for attempt in range(5):  # Increased retry attempts
                try:
                    bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)
                    bot.send_photo(ADMIN_ID, file_id, caption="📸 Registration Payment Screenshot")
                    admin_notify_success = True
                    logger.info(f"Admin notification sent for user {chat_id}")
                    break
                except Exception as notify_error:
                    logger.error(f"Admin notification error (attempt {attempt+1}): {notify_error}")
                    time.sleep(0.5 * (attempt + 1))  # Progressive delay

        # Send confirmation to user - edit the previous message for faster response
        try:
            bot.edit_message_text(
                """
╔═════《 📸 》═════╗
║ ✨ RECEIVED! ✨ ║
╚═════《 ⏳ 》═════╝

<b>🌟 Thank you for your registration! 🌟</b>

<b>🔍 Status:</b> Payment received, verification pending
<b>👁️ Next:</b> Our team will verify and activate your account
<b>📱 Notification:</b> You'll be alerted when ready

<i>💫 Get ready to shop on AliExpress with Ethiopian Birr!</i>
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
╔═════《 📸 》═════╗
║ ✨ RECEIVED! ✨ ║
╚═════《 ⏳ 》═════╝

<b>🌟 Thank you for your registration! 🌟</b>

<b>🔍 Status:</b> Payment received, verification pending
<b>👁️ Next:</b> Our team will verify and activate your account
<b>📱 Notification:</b> You'll be alerted when ready

<i>💫 Get ready to shop on AliExpress with Ethiopian Birr!</i>
""",
                parse_mode='HTML'
            )

        logger.info(f"Confirmation sent to user {chat_id}")
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

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')) and not call.data.startswith(('approve_deposit_', 'reject_deposit_')) and not call.data.startswith(('approve_order_', 'reject_order_')))
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
            logger.info(f"User {user_id} approved and added to database")

            # Send confirmation to user with enhanced welcome message
            bot.send_message(
                user_id,
                """
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been successfully activated and you're all set to start shopping on AliExpress using Ethiopian Birr!

<b>📱 Your Services:</b>
┌─────────────────┐
│ 💰 <b>Deposit</b> - Add funds to your account
│ 📦 <b>Submit Order</b> - Place AliExpress orders
│ 📊 <b>Order Status</b> - Track your orders
│ 💳 <b>Balance</b> - Check your current balance
└─────────────────┘

Need assistance? Use ❓ <b>Help Center</b> anytime!
""",
                parse_mode='HTML',
                reply_markup=create_main_menu(is_registered=True)
            )

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
def deposit_funds(message):
    """Handle deposit button"""
    chat_id = message.chat.id
    deposit_msg = """
💰 <b>Choose Deposit Amount</b>

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
💰 <b>Custom Deposit</b>

Enter amount in USD (1 USD = 160 birr).
Example: Enter 12 for $12 (1,920 birr)
""",
            parse_mode='HTML'
        )
        user_states[chat_id] = 'waiting_for_custom_amount'
        return

    amount = int(message.text.split('$')[1].split(' ')[0])
    send_payment_details(message, amount)

def send_payment_details(message, amount):
    """Send payment instructions"""
    chat_id = message.chat.id
    birr_amount = int(amount * 160)

    user_states[chat_id] = {
        'state': 'waiting_for_deposit_screenshot',
        'deposit_amount': amount
    }

    payment_msg = f"""
╔═══《 💳 》═══╗
║   Deposit   ║
╚═══《 💫 》═══╝

<b>💰 Amount Due:</b>
┌─────────────────┐
│ 🇺🇸 <code>${amount:,.2f}</code> USD
│ 🇪🇹 <code>{birr_amount:,}</code> ETB
└─────────────────┘

<b>💳 Payment Methods:</b>

🏦 <b>Commercial Bank (CBE)</b>
┌─────────────────┐
│ 💠 Account: <code>1000547241316</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

📱 <b>TeleBirr</b>
┌─────────────────┐
│ 💠 Number: <code>0986693062</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

<b>📝 Instructions:</b>
1️⃣ Choose payment method
2️⃣ Send exact amount
3️⃣ Take clear screenshot
4️⃣ Send screenshot below ⬇️
"""
    bot.send_message(chat_id, payment_msg, parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and isinstance(user_states[msg.chat.id], dict) and user_states[msg.chat.id].get('state') == 'waiting_for_deposit_screenshot', content_types=['photo'])
def handle_deposit_screenshot(message):
    """Process deposit screenshot"""
    chat_id = message.chat.id
    session = None
    try:
        file_id = message.photo[-1].file_id
        deposit_amount = user_states[chat_id].get('deposit_amount', 0)
        birr_amount = int(deposit_amount * 160)

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        pending_deposit = PendingDeposit(
            user_id=user.id,
            amount=deposit_amount
        )
        session.add(pending_deposit)
        session.commit()

        admin_markup = InlineKeyboardMarkup()
        admin_markup.row(
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_deposit_{chat_id}_{deposit_amount}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_deposit_{chat_id}_{deposit_amount}")
        )

        admin_msg = f"""
╔═══《 🔔 》═══╗
║ New Deposit ║
╚═══《 💫 》═══╝

👤 <b>User Details:</b>
┌─────────────────┐
│ Name: <b>{user.name}</b>
│ ID: <code>{chat_id}</code>
│ Phone: <code>{user.phone}</code>
└─────────────────┘

💰 <b>Amount:</b>
┌─────────────────┐
│ USD: <code>${deposit_amount:,.2f}</code>
│ ETB: <code>{birr_amount:,}</code>
└─────────────────┘

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📸 Screenshot attached below
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)
            bot.send_photo(ADMIN_ID, file_id, caption="📸 Deposit Screenshot")

        # Send enhanced fancy confirmation to user
        bot.send_message(
            chat_id,
            f"""
╔══════《 💰 》══════╗
║ ✨ DEPOSIT RECEIVED ✨ ║
╚══════《 ⏳ 》══════╝

<b>🌟 Thank you for your deposit! 🌟</b>

<b>💸 Deposit Information:</b>
┏━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 💵 Amount: <code>${deposit_amount:,.2f}</code>
┃ 🇪🇹 ETB: <code>{birr_amount:,}</code> birr
┃ 📤 Screenshot: <b>✅ Received</b>
┃ 🔄 Status: <b>⏳ Processing</b>
┗━━━━━━━━━━━━━━━━━━━━━━━━┛

<b>🚀 What happens next?</b>
┏━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 1️⃣ Quick verification of payment
┃ 2️⃣ Your balance will be updated
┃ 3️⃣ You'll receive confirmation
┃ 4️⃣ Start shopping immediately!
┗━━━━━━━━━━━━━━━━━━━━━━━━┛

<i>💫 Your AliExpress shopping adventure is just moments away!</i>
""",
            parse_mode='HTML'
        )

        del user_states[chat_id]

    except Exception as e:
        logger.error(f"Error processing deposit: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '💳 Balance')
def check_balance(message):
    """Check user balance"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if user:
            bot.send_message(
                chat_id,
                f"""
💳 <b>Your Balance</b>

Available: $<code>{user.balance:,.2f}</code>
≈ <code>{int(user.balance * 160):,}</code> ETB

Need more? Click 💰 Deposit
""",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error checking balance: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '👥 Join Community')
def join_community(message):
    """Join community button"""
    bot.send_message(
        message.chat.id,
        "Join our community: [AliExpress Tax](https://t.me/aliexpresstax)",
        parse_mode='Markdown'
    )

@bot.message_handler(func=lambda msg: msg.text == '📦 Submit Order')
def submit_order(message):
    """Handle submit order button"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(chat_id, "Please register first to submit an order.", reply_markup=create_main_menu(is_registered=False))
            return

        # Check if user has enough balance
        if user.balance <= 0:
            bot.send_message(
                chat_id,
                """
❌ <b>Insufficient Balance</b>

You need to add funds to your account before placing an order.
Click 💰 Deposit to add funds.
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
╔═════✨═════╗
📦 <b>NEW ORDER</b> 📦
╚═════✨═════╝

<b>🌟 Ready to shop on AliExpress? 🌟</b>

✅ <b>Just paste your product link below!</b>

Example:
<code>https://www.aliexpress.com/item/12345.html</code>

<i>Our team is ready to process your order immediately!</i>

Press 'Back to Main Menu' to cancel your order.
""",
            parse_mode='HTML',
            reply_markup=back_markup
        )
    except Exception as e:
        logger.error(f"Error in submit order: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_order_link')
def process_order_link(message):
    """Process the order link"""
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
            bot.send_message(chat_id, "🏠 Back to main menu",reply_markup=create_main_menu(is_registered=True))
            return
        finally:
            safe_close_session(session)

    # Basic validation of the link
    if not link.startswith('http') or 'aliexpress' not in link.lower():
        bot.send_message(
            chat_id,
            "❌ <b>Invalid Link</b>\n\nPlease provide a valid AliExpress product link that starts with 'http' and contains 'aliexpress'.\n\nOr press 'Back to Main Menu' to cancel.",
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
            amount=0.0  # Will be updated after review
        )
        session.add(new_order)
        session.commit()

        # Notify admin about the new order
        admin_markup = InlineKeyboardMarkup()
        admin_markup.row(
            InlineKeyboardButton("✅ Process", callback_data=f"process_order_{new_order.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_order_{new_order.id}")
        )

        admin_msg = f"""
╔═══《 🔔 》═══╗
║ New Order! ║
╚═══《 💫 》═══╝

👤 <b>Customer Details:</b>
┌─────────────────┐
│ 📛 Name: <b>{user.name}</b>
│ 📱 Phone: <code>{user.phone}</code>
│ 📍 Address: {user.address}
│ 🆔 User ID: <code>{chat_id}</code>
└─────────────────┘

💰 <b>Financial Details:</b>
┌─────────────────┐
│ 💳 Balance: $<code>{user.balance:.2f}</code>
│ 🛒 Order #: {new_order_number}
└─────────────────┘

🔗 <b>Product Link:</b>
<code>{link}</code>

⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)

        # Notify user about order submission with simple, beautiful design
        bot.send_message(
            chat_id,
            f"""
✨✨✨✨✨✨✨✨✨
    💫 <b>ORDER RECEIVED!</b> 💫
✨✨✨✨✨✨✨✨✨

🎉 <b>Order #{new_order_number} successfully placed!</b> 🎉

<b>Your AliExpress item is being processed right now.</b>

<i>Please wait while we prepare your:</i>
🔹 <b>Order ID</b>
🔹 <b>Tracking Number</b>

<b>We'll notify you as soon as these are ready!</b>

<i>Thank you for shopping with AliPay_ETH - Your Ethiopian gateway to AliExpress!</i>
""",
            parse_mode='HTML',
            reply_markup=create_main_menu(is_registered=True)
        )

        # Reset user state
        del user_states[chat_id]

    except Exception as e:
        logger.error(f"Error processing order link: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('process_order_', 'reject_order_')))
def handle_order_admin_decision(call):
    """Handle admin approval/rejection for orders"""
    session = None
    try:
        action, order_id = call.data.split('_order_')
        order_id = int(order_id)

        session = get_session()
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            bot.answer_callback_query(call.id, "Order not found.")
            return

        user = session.query(User).filter_by(id=order.user_id).first()

        if action == 'process':
            # Update order status
            order.status = 'Confirmed'
            session.commit()

            bot.send_message(
                user.telegram_id,
                f"""
✅ <b>Order Confirmed!</b>

📦 <b>Order #:</b> {order.order_number}
🔄 <b>Status:</b> Confirmed

We'll process your order and update you when it ships.
""",
                parse_mode='HTML'
            )

            bot.edit_message_text(
                "✅ Order processed!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        elif action == 'reject':
            # Update order status
            order.status = 'Rejected'
            session.commit()

            bot.send_message(
                user.telegram_id,
                f"""
❌ <b>Order Rejected</b>


@bot.message_handler(func=lambda msg: msg.text == '📅 Subscription')
def check_subscription(message):
    """Check user subscription status"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if user and user.subscription_date:
            current_time = datetime.utcnow()
            days_passed = (current_time - user.subscription_date).days
            days_remaining = max(0, 30 - days_passed)

            if days_remaining > 0:
                status = f"✅ Active ({days_remaining} days remaining)"
                from datetime import timedelta
                renewal_date = (user.subscription_date + timedelta(days=30)).strftime('%Y-%m-%d')
            else:
                status = "❌ Expired"
                renewal_date = "Now - Please renew"

            subscription_text = """
🗓️ <b>Subscription Status</b>

Status: """ + status + """
Next Payment: """ + renewal_date + """
Monthly Fee: $1.00 (150 ETB)

To renew your subscription, use /renewsub command.
"""
            bot.send_message(
                chat_id,
                subscription_text,
                parse_mode='HTML'
            )
        else:
            bot.send_message(chat_id, "Subscription information not available. Please contact support.")
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('process_order_', 'reject_order_')))
def handle_order_admin_decision(call):
    """Handle admin approval/rejection for orders"""
    session = None
    try:
        action, order_id = call.data.split('_order_')
        order_id = int(order_id)

        session = get_session()
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            bot.answer_callback_query(call.id, "Order not found.")
            return

        user = session.query(User).filter_by(id=order.user_id).first()

        if action == 'process':
            # Update order status
            order.status = 'Confirmed'
            session.commit()

            bot.send_message(
                user.telegram_id,
                f"""
✅ <b>Order Confirmed!</b>

📦 <b>Order #:</b> {order.order_number}
🔄 <b>Status:</b> Confirmed

We'll process your order and update you when it ships.
""",
                parse_mode='HTML'
            )

            bot.edit_message_text(
                "✅ Order processed!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        elif action == 'reject':
            # Update order status
            order.status = 'Rejected'
            session.commit()

            bot.send_message(
                user.telegram_id,
                f"""
❌ <b>Order Rejected</b>

📦 <b>Order #:</b> {order.order_number}
🔄 <b>Status:</b> Rejected

Please contact support for more information.
""",
                parse_mode='HTML'
            )

            bot.edit_message_text(
                f"❌ Order rejected!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        bot.answer_callback_query(call.id)

    except Exception as e:
        logger.error(f"Error in order admin decision: {e}")
        bot.answer_callback_query(call.id, "Error processing decision.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '📊 Order Status')
def check_order_status(message):
    """Check status of user's orders"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(chat_id, "Please register first to check orders.", reply_markup=create_main_menu(is_registered=False))
            return

        # Get user's orders
        orders = session.query(Order).filter_by(user_id=user.id).all()

        if not orders:
            bot.send_message(
                chat_id,
                """
📊 <b>Order Status</b>

You don't have any orders yet.
Click 📦 Submit Order to place your first order!
""",
                parse_mode='HTML'
            )
            return

        # Create message with order statuses
        status_msg = "📊 <b>Your Orders</b>\n\n"

        for order in orders:
            status_emoji = "🔄" if order.status == "Processing" else "✅" if order.status == "Confirmed" else "🚚" if order.status == "Shipped" else "❌"
            status_msg += f"""
<b>Order #{order.order_number}</b>
┌─────────────────┐
│ 🔄 Status: {status_emoji} {order.status}
│ 📅 Date: {order.created_at.strftime('%Y-%m-%d')}
"""
            if order.tracking_number:
                status_msg += f"│ 📦 Tracking: <code>{order.tracking_number}</code>\n"
            status_msg += "└─────────────────┘\n"

        bot.send_message(chat_id, status_msg, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Error checking order status: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '🔍 Track Order')
def track_order(message):
    """Track a specific order by number"""
    chat_id = message.chat.id

    bot.send_message(
        chat_id,
        """
🔍 <b>Track Order</b>

Please enter your order number:
Example: 1
""",
        parse_mode='HTML'
    )

    user_states[chat_id] = 'waiting_for_order_number'

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_order_number')
def process_order_tracking(message):
    """Process the order number for tracking"""
    chat_id = message.chat.id
    session = None

    try:
        order_number = int(message.text.strip())

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(chat_id, "Please register first to track orders.", reply_markup=create_main_menu(is_registered=False))
            return

        # Find the order
        order = session.query(Order).filter_by(user_id=user.id, order_number=order_number).first()

        if not order:
            bot.send_message(
                chat_id,
                f"❌ Order #{order_number} not found. Please check the number and try again.",
                parse_mode='HTML'
            )
            del user_states[chat_id]
            return

        # Show detailed order information
        tracking_info = f"""
🔍 <b>Order Details</b>

📦 <b>Order #{order.order_number}</b>
┌─────────────────┐
│ 🔄 Status: {order.status}
│ 📅 Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}
"""

        if order.tracking_number:
            tracking_info += f"""│ 📦 Tracking: <code>{order.tracking_number}</code>
│ 🔗 Track: https://global.cainiao.com/detail.htm?mailNoList={order.tracking_number}
"""
        else:
            tracking_info += "│ 📦 Tracking: Not available yet\n"

        if order.order_id:
            tracking_info += f"│ 🛒 Order ID: <code>{order.order_id}</code>\n"

        tracking_info += "└─────────────────┘"

        bot.send_message(chat_id, tracking_info, parse_mode='HTML')

        # Reset state
        del user_states[chat_id]

    except ValueError:
        bot.send_message(chat_id, "❌ Invalid order number. Please enter a number.")
    except Exception as e:
        logger.error(f"Error tracking order: {e}")
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '❓ Help Center')
def help_center(message):
    """Help center button"""
    help_msg = """
╔═══《 ❓ 》═══╗
║ Help Center ║
╚═══《 💫 》═══╝

📱 <b>Contact Support</b>
┌─────────────────┐
│ 👤 <b>@alipay_help_center</b>
└─────────────────┘

📖 <b>Quick Guide:</b>
┌─────────────────┐
│ • /start - Reset bot
│ • 🔑 Register - Join now
│ • 💰Deposit - Add funds
│ • 📦 Submit - New order
└─────────────────┘

🌟 <b>Need Help?</b>
┌─────────────────┐
│ • Orders: 📊 Status
│ • Track: 🔍 Package
│ • Money: 💳 Balance
└─────────────────┘

✨ We're here to help!
"""
    bot.send_message(message.chat.id, help_msg, parse_mode='HTML')

@bot.message_handler(commands=['updateorder'])
def update_order_details(message):
    """Admin command to update order details and notify user"""
    chat_id = message.chat.id
    session = None

    # Check if the sender is admin
    if not ADMIN_ID or int(chat_id) != int(ADMIN_ID):
        bot.send_message(chat_id, "❌ This command is for admin use only.")


def check_subscription_status():
    """Check for users with expired subscriptions and notify them"""
    session = None
    try:
        session = get_session()
        current_time = datetime.utcnow()
        from datetime import timedelta

        # Find users with subscriptions over 30 days old
        users = session.query(User).all()

        for user in users:
            if not user.subscription_date:
                continue

            days_passed = (current_time - user.subscription_date).days

            if days_passed >= 30:
                # Send notification about subscription renewal
                try:
                    # Check if we already sent a notification recently (within last 24 hours)
                    hours_since_last_update = 0
                    if hasattr(user, 'last_subscription_reminder'):
                        hours_since_last_update = (current_time - user.last_subscription_reminder).total_seconds() / 3600

                    # Only send reminder if we haven't sent one in the last 24 hours
                    if not hasattr(user, 'last_subscription_reminder') or hours_since_last_update >= 24:
                        payment_msg = f"""
╔═══《 🔔 》═══╗
║ SUBSCRIPTION RENEWAL ║
╚═══《 💫 》═══╝

<b>Hello {user.name}!</b>

Your monthly subscription has ended. To continue using AliPay_ETH services, please renew your subscription:

<b>💰 Subscription Fee:</b>
┌─────────────────┐
│ 🇺🇸 <code>$1.00</code> USD
│ 🇪🇹 <code>150</code> ETB
└─────────────────┘

<b>💳 Payment Methods:</b>

🏦 <b>Commercial Bank (CBE)</b>
┌─────────────────┐
│ 💠 Account: <code>1000547241316</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

📱 <b>TeleBirr</b>
┌─────────────────┐
│ 💠 Number: <code>0986693062</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

Please use /renewsub command to renew your subscription.
"""
                        bot.send_message(user.telegram_id, payment_msg, parse_mode='HTML')
                        logger.info(f"Sent subscription renewal notification to user {user.telegram_id}")

                        # Update notification timestamp to prevent spam
                        user.last_subscription_reminder = current_time
                        session.commit()

                except Exception as e:
                    logger.error(f"Failed to send subscription notification to {user.telegram_id}: {e}")

    except Exception as e:
        logger.error(f"Error checking subscription status: {e}")
        logger.error(traceback.format_exc())
    finally:
        safe_close_session(session)

# Run subscription check in a separate thread
import threading
def run_subscription_checker():
    """Run the subscription checker periodically"""
    while True:
        try:
            check_subscription_status()
            logger.info("Completed subscription status check")
        except Exception as e:
            logger.error(f"Error in subscription checker thread: {e}")

        # Wait for 24 hours before checking again
        time.sleep(24 * 60 * 60)

# Start the subscription checker in the run_bot function

        logger.error(f"Unauthorized /updateorder attempt from user {chat_id}. Admin ID is {ADMIN_ID}")
        return

    try:
        # Command format: /updateorder user_id order_number tracking_number order_id
        parts = message.text.split()

        if len(parts) < 5:
            bot.send_message(
                chat_id, 
                """
❌ <b>Invalid format</b>

Correct format:
/updateorder [user_id] [order_number] [tracking_number] [order_id]

Example:
/updateorder 123456789 1 LY123456789CN ALI1234567890
""", 
                parse_mode='HTML'
            )
            return

        user_id = int(parts[1])
        order_number = int(parts[2])
        tracking_number = parts[3]
        order_id = parts[4]

        session = get_session()

        # Get the user
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            bot.send_message(chat_id, f"❌ User with ID {user_id} not found.")
            return

        # Get the order
        order = session.query(Order).filter_by(user_id=user.id, order_number=order_number).first()
        if not order:
            bot.send_message(chat_id, f"❌ Order #{order_number} for user {user_id} not found.")
            return

        # Update order details
        order.tracking_number = tracking_number
        order.order_id = order_id
        order.status = 'Shipped'
        session.commit()

        # Send notification to user
        user_notification = f"""
✅ <b>Order Shipped!</b>

📦 <b>Order Details Updated:</b>
┌─────────────────┐
│ 📊 Order #: <b>{order_number}</b>
│ 🆔 Order ID: <code>{order_id}</code>
│ 📦 Tracking #: <code>{tracking_number}</code>
│ 💰 Balance: $<code>{user.balance:.2f}</code>
└─────────────────┘

🔍 <b>Track your package:</b>
https://global.cainiao.com/detail.htm?mailNoList={tracking_number}

Thank you for shopping with AliPay_ETH!
"""
        bot.send_message(user_id, user_notification, parse_mode='HTML')

        # Confirm to admin
        bot.send_message(
            chat_id, 
            f"""
✅ <b>Order updated successfully!</b>

User <b>{user.name}</b> ({user_id}) has been notified about:
- Order #{order_number}
- Tracking: {tracking_number}
- Order ID: {order_id}
- Balance: ${user.balance:.2f}
""", 
            parse_mode='HTML'
        )

    except ValueError as e:
        bot.send_message(chat_id, f"❌ Invalid input. Please check user ID and order number are numeric.")
    except Exception as e:
        logger.error(f"Error updating order: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, f"❌ Error: {str(e)}")
    finally:
        safe_close_session(session)

@bot.message_handler(commands=['renewsub'])
def renew_subscription(message):
    """Command to manually renew subscription"""
    chat_id = message.chat.id

    # Set state for waiting for screenshot
    user_states[chat_id] = {
        'state': 'waiting_for_subscription_screenshot',
    }

    payment_msg = f"""
╔═══《 💳 》═══╗
║   SUBSCRIPTION   ║
╚═══《 💫 》═══╝

<b>💰 Monthly Fee:</b>
┌─────────────────┐
│ 🇺🇸 <code>$1.00</code> USD
│ 🇪🇹 <code>150</code> ETB
└─────────────────┘

<b>💳 Payment Methods:</b>

🏦 <b>Commercial Bank (CBE)</b>
┌─────────────────┐
│ 💠 Account: <code>1000547241316</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

📱 <b>TeleBirr</b>
┌─────────────────┐
│ 💠 Number: <code>0986693062</code>
│ 👤 Name: <b>Eyob Mulugeta</b>
└─────────────────┘

<b>📝 Instructions:</b>
1️⃣ Choose payment method
2️⃣ Send exact amount
3️⃣ Take clear screenshot
4️⃣ Send screenshot below ⬇️
"""
    bot.send_message(chat_id, payment_msg, parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.chat.id in user_states and isinstance(user_states[msg.chat.id], dict) and user_states[msg.chat.id].get('state') == 'waiting_for_subscription_screenshot', content_types=['photo'])
def handle_subscription_screenshot(message):
    """Process subscription renewal screenshot"""
    chat_id = message.chat.id
    session = None
    try:
        file_id = message.photo[-1].file_id

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(chat_id, "User not found. Please register first.")
            return

        # Admin markup for approval/rejection
        admin_markup = InlineKeyboardMarkup()
        admin_markup.row(
            InlineKeyboardButton("✅ Approve Sub", callback_data=f"approve_sub_{chat_id}"),
            InlineKeyboardButton("❌ Reject Sub", callback_data=f"reject_sub_{chat_id}")
        )

        # Admin notification
        admin_msg = f"""
╔═══《 🔔 》═══╗
║ Subscription Renewal ║
╚═══《 💫 》═══╝

👤 <b>User Details:</b>
┌─────────────────┐
│ Name: <b>{user.name}</b>
│ ID: <code>{chat_id}</code>
│ Phone: <code>{user.phone}</code>
└─────────────────┘

💰 <b>Amount:</b> $1.00 (150 ETB)
⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📸 Screenshot attached below
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)
            bot.send_photo(ADMIN_ID, file_id, caption="📸 Subscription Payment Screenshot")

        # User confirmation
        bot.send_message(
            chat_id,
            """
╔══════《 💰 》══════╗
║ ✨ PAYMENT RECEIVED ✨ ║
╚══════《 ⏳ 》══════╝

<b>🌟 Thank you for your subscription payment! 🌟</b>

<b>💸 Payment Information:</b>
┏━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ 💵 Amount: <code>$1.00</code>
┃ 🇪🇹 ETB: <code>150</code> birr
┃ 📤 Screenshot: <b>✅ Received</b>
┃ 🔄 Status: <b>⏳ Processing</b>
┗━━━━━━━━━━━━━━━━━━━━━━━━┛

<b>🚀 Your subscription will be renewed shortly!</b>
""",
            parse_mode='HTML'
        )

        # Clear state
        if chat_id in user_states:
            del user_states[chat_id]

    except Exception as e:
        logger.error(f"Error processing subscription payment: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(chat_id, "Sorry, there was an error. Please try again.")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_sub_', 'reject_sub_')))
def handle_subscription_admin_decision(call):
    """Handle admin approval/rejection for subscription payments"""
    session = None
    try:
        parts = call.data.split('_')
        action = parts[0]
        chat_id = int(parts[2])

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.answer_callback_query(call.id, "User not found")
            return

        if action == 'approve':
            # Update subscription date
            user.subscription_date = datetime.utcnow()
            session.commit()

            # Notify user
            bot.send_message(
                chat_id,
                """
╔══════《 💎 》══════╗
║ ✅ SUBSCRIPTION RENEWED! ✅ ║
╚══════《 💫 》══════╝

<b>🎉 Your monthly subscription has been renewed!</b>

<b>⏱️ Valid until:</b> 1 month from today

<i>Thank you for continuing to use AliPay_ETH!</i>
""",
                parse_mode='HTML'
            )

            # Update admin message
            bot.edit_message_text(
                f"✅ Subscription renewed for {user.name}!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        elif action == 'reject':
            bot.send_message(
                chat_id,
                "❌ Subscription payment rejected. Please try again with a clearer payment screenshot.",
                parse_mode='HTML'
            )

            bot.edit_message_text(
                f"❌ Subscription renewal rejected for {user.name}!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        bot.answer_callback_query(call.id, text="Processed successfully")
    except Exception as e:
        logger.error(f"Error in subscription admin decision: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing decision")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_deposit_', 'reject_deposit_')))
def handle_deposit_admin_decision(call):
    """Handle admin approval/rejection for deposits"""
    session = None
    try:
        parts = call.data.split('_')
        action = parts[0]
        chat_id = int(parts[2])
        amount = float(parts[3])

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.answer_callback_query(call.id, "User not found")
            return

        pending_deposit = session.query(PendingDeposit).filter_by(user_id=user.id, amount=amount).first()

        if not pending_deposit:
            bot.answer_callback_query(call.id, "No pending deposit found")
            return

        if action == 'approve':
            user.balance += amount
            session.delete(pending_deposit)
            session.commit()

            bot.send_message(
                chat_id,
                f"""
╔══════《 💎 》══════╗
║ ✅ DEPOSIT APPROVED! ✅ ║
╚══════《 💫 》══════╝

<b>💰 Amount Added:</b> $<code>{amount:,.2f}</code>
<b>💳 Current Balance:</b> $<code>{user.balance:,.2f}</code>

<b>🚀 Ready for Shopping!</b>
You can now submit your order using the 📦 <b>Submit Order</b> button.

<i>Thank you for using AliPay_ETH!</i>
""",
                parse_mode='HTML'
            )
            bot.edit_message_text(
                f"✅ Deposit of ${amount:.2f} approved for {user.name}!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        elif action == 'reject':
            session.delete(pending_deposit)
            session.commit()

            bot.send_message(
                chat_id,
                "❌ Deposit rejected. Please try again with a clearer payment screenshot.",
                parse_mode='HTML'
            )
            bot.edit_message_text(
                f"❌ Deposit of ${amount:.2f} rejected for {user.name}!",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        bot.answer_callback_query(call.id, text="Processed successfully")
    except Exception as e:
        logger.error(f"Error in deposit admin decision: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing decision")
    finally:
        safe_close_session(session)


@bot.message_handler(func=lambda msg: msg.chat.id in user_states and user_states[msg.chat.id] == 'waiting_for_custom_amount')
def handle_custom_deposit_amount(message):
    """Handle custom deposit amount"""
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

            # Clear state
            del user_states[chat_id]
        except Exception as e:
            logger.error(f"Error returning to main menu: {e}")
            bot.send_message(chat_id, "🏠 Back to main menu", reply_markup=create_main_menu(is_registered=True))
        finally:
            safe_close_session(session)
        return

    try:
        amount = float(message.text)
        if amount <= 0:
            bot.send_message(chat_id, "Please enter a valid positive amount.")
            return
        send_payment_details(message, amount)
    except ValueError:
        bot.send_message(chat_id, "Invalid amount. Please enter a number.")


def run_bot():
    """Run bot with enhanced resilience and recovery"""
    global shutdown_requested
    retry_count = 0
    start_time = time.time()
    last_success = time.time()
    max_quick_retries = 5

    # Track active handlers for improved reliability
    active_handlers = {}

    while not shutdown_requested:
        try:
            logger.info("🚀 Starting bot...")

            # Aggressive webhook cleanupto prevent conflicts
            for cleanup_attempt in range(3):
                try:
                    bot.delete_webhook(drop_pending_updates=True)
                    logger.info("✅ Webhook cleared with pending updates dropped")
                    break
                except Exception as e:
                    logger.error(f"❌ Webhook cleanup error (attempt {cleanup_attempt+1}): {e}")
                    time.sleep(2)

            # Test connection with retries
            connection_success = False
            for attempt in range(3):
                try:
                    bot_info = bot.get_me()
                    logger.info(f"✅ Connected as @{bot_info.username}")
                    connection_success = True
                    break
                except Exception as e:
                    logger.error(f"❌ Connection test error (attempt {attempt+1}): {e}")
                    time.sleep(2)

            if not connection_success:
                logger.error("❌ Failed to establish Telegram connection after multiple attempts")
                raise Exception("Telegram API connection failed")

            # Initialize database with validation
            try:
                init_db()
                logger.info("✅ Database initialized")

                # Comprehensive database validation
                from sqlalchemy import text, inspect
                session = get_session()
                session.execute(text("SELECT 1"))

                # Check all expected tables exist
                inspector = inspect(engine)
                required_tables = ['users', 'orders', 'pending_approvals', 'pending_deposits']
                existing_tables = inspector.get_table_names()

                missing_tables = [table for table in required_tables if table not in existing_tables]
                if missing_tables:
                    logger.warning(f"⚠️ Missing tables in database: {missing_tables}")
                    # Consider auto-fixing here if needed

                session.close()
                logger.info("✅ Database connection and schema verified")
            except Exception as e:
                logger.error(f"❌ Database initialization error: {e}")
                logger.error(traceback.format_exc())
                raise

            # Enhanced heartbeat with connection testing
            def send_heartbeat():
                heartbeat_interval = 30  # seconds
                connection_failures = 0
                max_failures = 5

                while True:
                    try:
                        logger.info("💓 Bot process is running...")

                        # Test database connection
                        try:
                            session = get_session()
                            session.execute(text("SELECT 1"))
                            session.close()
                        except Exception as db_error:
                            logger.error(f"❌ Database connection error in heartbeat: {db_error}")

                        # Verify bot connection is still active
                        bot_info = bot.get_me()
                        logger.info(f"✅ Connection verified as @{bot_info.username}")
                        connection_failures = 0  # Reset failure counter on success

                        # Track handler responsiveness metrics here if needed
                        # This could be expanded to detect slow handlers

                        time.sleep(heartbeat_interval)
                    except Exception as e:
                        connection_failures += 1
                        logger.error(f"❌ Bot connection error in heartbeat ({connection_failures}/{max_failures}): {e}")

                        if connection_failures >= max_failures:
                            logger.critical("🚨 Multiple connection failures detected, forcing bot restart")
                            # This will exit this thread and allow main thread to restart bot
                            return

                        time.sleep(5)  # Shorter sleep on failure

            # Start enhanced heartbeat in separate thread
            import threading
            heartbeat_thread = threading.Thread(target=send_heartbeat, daemon=True)
            heartbeat_thread.start()

            # Start subscription checker in separate thread with error handling
            def subscription_checker_wrapper():
                try:
                    run_subscription_checker()
                except Exception as e:
                    logger.error(f"Subscription checker error: {e}")
                    logger.error(traceback.format_exc())

            subscription_thread = threading.Thread(target=subscription_checker_wrapper, daemon=True)
            subscription_thread.start()
            logger.info("🔄 Subscription checker started")

            # Use optimized polling parameters
            logger.info("🤖 Starting infinity polling with optimized parameters...")
            bot.infinity_polling(
                timeout=30,               # Reduced timeout for faster error detection
                long_polling_timeout=45,  # Slightly increased to reduce API calls but still responsive
                allowed_updates=[         # Only get updates we actually handle
                    "message", 
                    "edited_message", 
                    "callback_query"
                ],
                logger_level=logging.INFO,
                skip_pending=True         # Skip pending updates for clean restart
            )

            # If we reach here, polling has ended (should not happen with infinity_polling)
            logger.warning("⚠️ Polling loop exited unexpectedly")

        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Bot error (attempt {retry_count}): {traceback.format_exc()}")

            # Exponential backoff for retries to prevent API rate limiting
            if retry_count <= max_quick_retries:
                # Quick retries with short delay for temporary issues
                wait_time = 3
            else:
                # Exponential backoff for persistent issues, max 60 seconds
                wait_time = min(60, 5 * (2 ** min(retry_count - max_quick_retries, 5)))

            # Reset retry count after successful runtime
            if time.time() - last_success > 3600:  # 1 hour
                retry_count = 0
                start_time = time.time()
                last_success = time.time()

            logger.info(f"⏳ Waiting {wait_time} seconds before restart...")
            time.sleep(wait_time)

if __name__ == "__main__":
    logger.info("🤖 Bot initializing...")
    try:
        run_bot()
    except KeyboardInterrupt:
        logger.info("👋 Bot shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Fatal error: {traceback.format_exc()}")
        time.sleep(5)  # Wait before exiting to prevent instant restarts
        sys.exit(1)

#!/usr/bin/env python3
"""
Telegram Bot Runner with enhanced functionality
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
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import init_db, get_session, safe_close_session
from models import User, Order, PendingApproval, PendingDeposit
from datetime import datetime, timedelta

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
• USD: <code>$1.00</code>
• ETB: <code>150</code>

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
• USD: <code>$1.00</code>
• ETB: <code>150</code>

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
                        f"""
⚠️⚠️⚠️ ALREADY PENDING ⚠️⚠️⚠️

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
New User!

User Information:
Name: <b>{registration_data[chat_id]['name']}</b>
Address: {registration_data[chat_id]['address']}
Phone: <code>{registration_data[chat_id]['phone']}</code>
ID: <code>{chat_id}</code>

Registration Fee: $1 (150 ETB)
Payment screenshot attached below
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please verify the payment and approve or reject.
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
                f"""
📷📷📷 ✨ RECEIVED! ✨ 🕘🕘🕘

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
✨ RECEIVED! ✨ 

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
• Pay the $1 registration fee

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
  Earn rewards for inviting friends

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
            logger.info(f"User {user_id} approved and added to database")

            # Send confirmation to user with enhanced welcome message
            bot.send_message(
                user_id,
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
        send_payment_details(message, amount)
    else:
        bot.send_message(
            message.chat.id,
            "❌ Invalid amount format. Please try again.",
            parse_mode='HTML'
        )
   

def send_payment_details(message, amount):
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

<i>💎 Your balance will update automatically after payment! 💎</i>
<i>No need to send screenshots with online payment</i>
"""
            bot.send_message(chat_id, payment_msg, parse_mode='HTML', reply_markup=markup)

            # Store transaction reference
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Processing'
            )
            session.add(pending_deposit)
            session.commit()

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
            birr_amount = int(usd_amount * 160)
        else:
            # User entered birr, convert to USD
            birr_amount = int(float(clean_amount))
            usd_amount = birr_amount / 160

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
        send_payment_details(message, usd_amount)

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
New Deposit

User Details:
Name: <b>{user.name}</b>
ID: <code>{chat_id}</code>
Phone: <code>{user.phone}</code>

Amount:
USD: <code>${deposit_amount:,.2f}</code>
ETB: <code>{birr_amount:,}</code>

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Screenshot attached below
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)
            bot.send_photo(ADMIN_ID, file_id, caption="📸 Deposit Screenshot")

        # Send enhanced fancy confirmation to user
        bot.send_message(
            chat_id,
            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✨ <b>DEPOSIT RECEIVED</b> ✨  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

🌟 <b>Thank you for your deposit!</b> 🌟

<b>💰 DEPOSIT INFORMATION:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${deposit_amount:,.2f}
• Status: ⏳ <b>Processing</b>
• Screenshot: ✅ <b>Received</b>

<b>🔄 WHAT HAPPENS NEXT:</b>
1️⃣ Our team verifies your payment
2️⃣ Your balance is updated automatically
3️⃣ You'll receive confirmation message
4️⃣ Start shopping immediately!

<i>💫 Your AliExpress shopping adventure is just moments away! 💫</i>
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
            birr_balance = int(user.balance * 160)
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>YOUR BALANCE</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Available:</b> <code>{birr_balance:,}</code> birr
≈ $<code>{user.balance:,.2f}</code> USD

<i>Need more? Click 💰 Deposit</i>
""",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error checking balance:{e}")
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
        if user.balance <= 0:
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

    # First, send immediate acknowledgment
    processing_msg = bot.send_message(
        chat_id,
        "⏳ <b>Processing your order...</b>",
        parse_mode='HTML'
    )

    # Basic validation of the link
    if not link.startswith('http') or 'aliexpress' not in link.lower():
        bot.edit_message_text(
            """
❌ <b>INVALID LINK DETECTED</b>

Please provide a valid AliExpress product link that:
• Starts with 'http' or 'https'
• Contains 'aliexpress' in the URL

<b>Example:</b>
<code>https://www.aliexpress.com/item/1005006383458726.html</code>

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
<code>{link}</code>

<b>⏰ TIME:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<i>Please review and process this order</i>
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)

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

<b>🔍 WHAT HAPPENS NEXT?</b>
1️⃣ Our team will process your order immediately
2️⃣ You'll receive confirmation when approved
3️⃣ Your order ID will be generated
4️⃣ Tracking details will be provided when shipped

<b>📱 STAY UPDATED:</b>
Use "<b>🔍 Track Order</b>" button anytime to check your order status!

<i>Thank you for shopping with AliPay_ETH - Your Ethiopian gateway to AliExpress!</i>
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

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_deposit_', 'reject_deposit_')))
def handle_deposit_admin_decision(call):
    """Handle admin approval/rejection for deposits"""
    session = None
    try:
        parts = call.data.split('_')
        action = parts[0]  # Now "approve" or "reject"
        deposit_marker = parts[1]  # This will be "deposit"
        chat_id = int(parts[2])
        amount = float(parts[3])

        logger.info(f"Processing deposit {action} for user {chat_id}, amount: ${amount}")

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.answer_callback_query(call.id, "User not found")
            logger.error(f"User {chat_id} not found for deposit {action}")
            return

        pending_deposit = session.query(PendingDeposit).filter_by(user_id=user.id, amount=amount, status='Processing').first()

        if not pending_deposit:
            bot.answer_callback_query(call.id, "No matching pending deposit found")
            logger.warning(f"No pending deposit found for user {chat_id} with amount ${amount}")
            return

        if action == 'approve':
            # Add amount to user balance
            user.balance += amount
            pending_deposit.status = 'Approved'
            session.commit()

            # Notify user
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{int(amount * 160):,}</code> birr
• USD Value: ${amount:.2f}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
""",
                parse_mode='HTML'
            )

            # Update admin message
            bot.edit_message_text(
                f"✅ Deposit of ${amount:.2f} approved for {user.name}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        elif action == 'reject':
            # Mark as rejected without changing balance
            pending_deposit.status = 'Rejected'
            try:
                session.commit()
            except Exception as commit_error:
                logger.error(f"Error committing rejection: {commit_error}")
                session.rollback()
                raise

            # Notify user
            bot.send_message(
                chat_id,
                f"""
❌ DEPOSIT REJECTED ❌

Your deposit of ${amount:.2f} was rejected.

Possible reasons:
• Payment amount didn't match
• Payment screenshot unclear
• Payment not received

Please try again or contact support.
""",
                parse_mode='HTML'
            )

            # Update admin message
            bot.edit_message_text(
                f"❌ Deposit of ${amount:.2f} rejected for {user.name}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )

        bot.answer_callback_query(call.id, "Action processed successfully")

    except Exception as e:
        logger.error(f"Error processing deposit decision: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing decision")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('process_order_', 'reject_order_')))
def handle_order_admin_decision(call):
    """Handle admin approval/rejection for orders with enhanced user notifications"""
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

            # Generate a dummy order ID if none exists (can be set manually later)
            if not order.order_id:
                # Format: AE-{user_id}-{order_number}-{random numbers}
                import random
                random_suffix = ''.join([str(random.randint(0, 9)) for _ in range(4)])
                order.order_id = f"AE-{user.id}-{order.order_number}-{random_suffix}"

            # Deduct order amount from user balance if amount is set
            if order.amount and order.amount > 0:
                if user.balance >= order.amount:
                    user.balance -= order.amount
                    logger.info(f"Deducted ${order.amount} from user {user.id}'s balance for order {order.id}")
                else:
                    logger.warning(f"Insufficient balance: User {user.id} has ${user.balance} but order {order.id} costs ${order.amount}")

            session.commit()

            # Send enhanced confirmation to user with tracking instructions
            bot.send_message(
                user.telegram_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>ORDER CONFIRMED!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

🎁 <b>Congratulations!</b> Your order has been processed!

📦 <b>Order Details:</b>
• Order #: <code>{order.order_number}</code>
• Order ID: <code>{order.order_id}</code>
• Status: <b>Confirmed</b>
• Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}

🔍 <b>Track Your Order:</b>
Use the "<b>🔍 Track Order</b>" button anytime to get 
the latest status and tracking information!

📱 <b>What's Next?</b>
• We'll process your order right away
• You'll receive shipping confirmation soon
• All updates will be available in tracking

<i>Thank you for shopping with AliPay_ETH!</i>
""",
                parse_mode='HTML'
            )

            # Update admin message with more details
            bot.edit_message_text(
                f"""
✅ <b>Order Processed Successfully!</b>

Order #: {order.order_number}
Order ID: <code>{order.order_id}</code>
Customer: {user.name}
Phone: <code>{user.phone}</code>

<i>Order has been confirmed and customer has been notified.</i>
""",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='HTML'
            )

        elif action == 'reject':
            # Update order status
            order.status = 'Rejected'
            session.commit()

            # Enhanced rejection message
            bot.send_message(
                user.telegram_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❌ <b>ORDER REJECTED</b> ❌  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

We regret to inform you that your order could not be processed.

📦 <b>Order Details:</b>
• Order #: <code>{order.order_number}</code>
• Status: <b>Rejected</b>

<b>Possible reasons:</b>
• Out of stock item
• Pricing discrepancy
• Shipping restrictions
• Payment issues

Please contact our support team for assistance or place a new order.

<i>We apologize for any inconvenience caused.</i>
""",
                parse_mode='HTML'
            )

            # Update admin message
            bot.edit_message_text(
                f"""
❌ <b>Order Rejected</b>

Order #: {order.order_number}
Customer: {user.name}
Phone: <code>{user.phone}</code>

<i>Customer has been notified of the rejection.</i>
""",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='HTML'
            )

        bot.answer_callback_query(call.id, "Order processed successfully")

    except Exception as e:
        logger.error(f"Error in order admin decision: {e}")
        logger.error(traceback.format_exc())
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
Status: {status_emoji} {order.status}
Date: {order.created_at.strftime('%Y-%m-%d')}
"""
            if order.tracking_number:
                status_msg += f"Tracking: <code>{order.tracking_number}</code>\n"
            status_msg += "\n"

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
    """Process the order number for tracking with enhanced visualization"""
    chat_id = message.chat.id
    session = None

    try:
        order_number = int(message.text.strip())

        # Send immediate acknowledgment to improve user experience
        processing_msg = bot.send_message(
            chat_id,
            "🔎 <b>Searching for your order...</b>",
            parse_mode='HTML'
        )

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.edit_message_text(
                "Please register first to track orders.",
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                reply_markup=create_main_menu(is_registered=False)
            )
            return

        # Find the order
        order = session.query(Order).filter_by(user_id=user.id, order_number=order_number).first()

        if not order:
            bot.edit_message_text(
                f"""
❌ <b>Order Not Found</b>

We couldn't find Order #{order_number} in your account.
• Check if the order number is correct
• Make sure the order belongs to your account
• Try again with a different order number

<i>Need help? Use the ❓ Help Center button.</i>
""",
                chat_id=chat_id,
                message_id=processing_msg.message_id,
                parse_mode='HTML'
            )
            del user_states[chat_id]
            return

        # Get status emoji
        status_emoji = {
            'Processing': '⏳',
            'Confirmed': '✅',
            'Shipped': '🚚',
            'Delivered': '📦',
            'Rejected': '❌',
            'Cancelled': '🚫'
        }.get(order.status, '🔄')

        # Show detailed order information with enhanced styling
        product_link_short = order.product_link[:40] + "..." if len(order.product_link) > 40 else order.product_link

        tracking_info = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>ORDER TRACKING</b> 🔍  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>📦 ORDER DETAILS</b>
• Number: <code>{order.order_number}</code>
• Status: {status_emoji} <b>{order.status}</b>
• Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}
"""

        if order.order_id:
            tracking_info += f"• Order ID: <code>{order.order_id}</code>\n"

        if order.tracking_number:
            tracking_info += f"""
<b>📱 TRACKING INFORMATION</b>
• Tracking #: <code>{order.tracking_number}</code>
• Track URL: <a href="https://global.cainiao.com/detail.htm?mailNoList={order.tracking_number}">Click to track</a>
"""
        else:
            tracking_info += """
<b>📱 TRACKING INFORMATION</b>
• Tracking #: <i>Not available yet</i>
• <i>You'll be notified when your package ships</i>
"""

        tracking_info += f"""
<b>🔗 PRODUCT INFORMATION</b>
• <a href="{order.product_link}">View Product</a>

<i>Your order status will be updated automatically.
Please contact support if you have any questions.</i>
"""

        # Add inline keyboard for tracking link if available
        markup = None
        if order.tracking_number:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton(
                "🔍 Track Package Online",
                url=f"https://global.cainiao.com/detail.htm?mailNoList={order.tracking_number}"
            ))

        bot.edit_message_text(
            tracking_info,
            chat_id=chat_id,
            message_id=processing_msg.message_id,
            parse_mode='HTML',
            reply_markup=markup,
            disable_web_page_preview=True
        )

        # Reset state
        del user_states[chat_id]

    except ValueError:
        bot.send_message(
            chat_id,
            """
❌ <b>Invalid Input</b>

Please enter a valid order number (numbers only).
Example: <code>1</code>
""",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error tracking order: {e}")
        logger.error(traceback.format_exc())
        bot.send_message(
            chat_id,
            "Sorry, there was an error. Please try again.",
            reply_markup=create_main_menu(is_registered=True)
        )
    finally:
        safe_close_session(session)

@bot.message_handler(func=lambda msg: msg.text == '❓ Help Center')
def help_center(message):
    """Enhanced help center with beautiful formatting"""

    # Create fancy help center keyboard with direct contact options
    help_markup = InlineKeyboardMarkup(row_width=2)
    help_markup.add(
        InlineKeyboardButton("✨ Tutorials ✨", callback_data="tutorials"),
        InlineKeyboardButton("❓ FAQs ❓", callback_data="faqs")
    )
    help_markup.add(
        InlineKeyboardButton("💬 Chat with Support", url="https://t.me/alipay_help_center"),
        InlineKeyboardButton("📱 Contact Admin", url="https://t.me/alipay_eth_admin")
    )

    help_msg = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🌟 <b>WELCOME TO HELP CENTER</b> 🌟  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>✨ Need assistance? We've got you covered! ✨</b>

<b>📚 QUICK COMMANDS</b>
• 🏠 <code>/start</code> - Reset bot
• 🔑 <code>Register</code> - Join now
• 💰 <code>Deposit</code> - Add funds
• 📦 <code>Submit</code> - New order

<b>📱 SUPPORT GUIDE</b>
• 📊 Order Status - Check progress
• 🔍 Track Order - Follow shipment
• 💳 Balance - View your funds
• 📅 Subscription - Manage account

<b>💎 PREMIUM SUPPORT 💎</b>
Our dedicated team is available 24/7 to assist you with all your shopping needs! Click the buttons below for instant support.

<i>We're committed to making your AliExpress shopping experience seamless and enjoyable!</i>
"""
    bot.send_message(message.chat.id, help_msg, parse_mode='HTML', reply_markup=help_markup)

@bot.message_handler(commands=['setorderamount'])
def set_order_amount(message):
    """Set the amount for an order"""
    chat_id = message.chat.id

    # Check if user is admin
    if chat_id != ADMIN_ID:
        logger.error(f"Unauthorized /setorderamount attempt from user {chat_id}. Admin ID is {ADMIN_ID}")
        return

    try:
        # Parse command: /setorderamount order_number amount
        parts = message.text.split()
        if len(parts) != 3:
            bot.reply_to(message, "Usage: /setorderamount [order_number] [amount]")
            return

        order_number = parts[1]
        try:
            amount = float(parts[2])
        except ValueError:
            bot.reply_to(message, "Amount must be a number")
            return

        session = get_session()
        order = session.query(Order).filter_by(order_number=order_number).first()

        if not order:
            bot.reply_to(message, f"❌ Order #{order_number} not found")
            safe_close_session(session)
            return

        # Update order amount
        old_amount = order.amount
        order.amount = amount
        session.commit()

        bot.reply_to(message, f"✅ Order #{order_number} amount updated from ${old_amount:.2f} to ${amount:.2f}")

    except Exception as e:
        logger.error(f"Error setting order amount: {e}")
        logger.error(traceback.format_exc())
        bot.reply_to(message, "❌ Error setting order amount")
    finally:
        safe_close_session(session)

@bot.message_handler(commands=['updateorder'])
def handle_order_admin_decision(message):
    """Handle comprehensive order status updates from admin"""
    chat_id = message.chat.id

    # Check if user is admin
    if chat_id != ADMIN_ID:
        logger.error(f"Unauthorized /updateorder attempt from user {chat_id}. Admin ID is {ADMIN_ID}")
        return

    try:
        # Extract command parts
        parts = message.text.split(maxsplit=2)

        # Help message for command usage
        if len(parts) < 2 or parts[1].lower() == 'help':
            help_text = """
<b>Order Update Commands:</b>

<b>Basic update:</b>
/updateorder <order_number> <status>
Example: <code>/updateorder 1 shipped</code>

<b>Update with details:</b>
/updateorder <order_number> <field>:<value> [<field>:<value>...]
Example: <code>/updateorder 1 status:shipped tracking:LX123456789CN</code>

<b>Valid status values:</b> processing, confirmed, shipped, delivered, cancelled

<b>Valid fields:</b>
• status - Order status
• tracking - Tracking number
• orderid - AliExpress order ID

<b>Examples:</b>
<code>/updateorder 2 status:shipped tracking:LX123456789CN orderid:9283746563</code>
<code>/updateorder 3 tracking:LX987654321CN</code>
"""
            bot.reply_to(message, help_text, parse_mode='HTML')
            return

        order_number = parts[1]

        # Check if we have more parameters
        if len(parts) < 3:
            bot.reply_to(message, "Please specify status or field:value pairs. Use /updateorder help for instructions.")
            return

        # Get the session and find the order
        session = get_session()
        order = session.query(Order).filter_by(order_number=order_number).first()

        if not order:
            bot.reply_to(message, f"❌ Order #{order_number} not found")
            safe_close_session(session)
            return

        # Get the user
        customer = session.query(User).filter_by(id=order.user_id).first()
        if not customer:
            bot.reply_to(message, f"❌ User for Order #{order_number} not found")
            safe_close_session(session)
            return

        # Parse the update parameters
        update_params = parts[2]

        # Check if this is a simple status update
        if ':' not in update_params:
            # Legacy format: /updateorder <order_id> <status>
            new_status = update_params.lower()

            # Validate status
            valid_statuses = ['processing', 'confirmed', 'shipped', 'delivered', 'cancelled']
            if new_status not in valid_statuses:
                bot.reply_to(message, f"Invalid status. Use one of: {', '.join(valid_statuses)}")
                return

            # Update only status
            order.status = new_status
            order.updated_at = datetime.utcnow()
        else:
            # New format: /updateorder <order_id> field1:value1 field2:value2
            params = update_params.split()
            updates = {}

            for param in params:
                if ':' not in param:
                    continue

                field, value = param.split(':', 1)

                if field == 'status':
                    valid_statuses = ['processing', 'confirmed', 'shipped', 'delivered', 'cancelled']
                    if value.lower() not in valid_statuses:
                        bot.reply_to(message, f"Invalid status '{value}'. Use one of: {', '.join(valid_statuses)}")
                        return
                    updates['status'] = value.lower()
                elif field == 'tracking':
                    updates['tracking_number'] = value
                elif field == 'orderid':
                    updates['order_id'] = value

            # Apply all updates
            for field, value in updates.items():
                setattr(order, field, value)

            order.updated_at = datetime.utcnow()

        # Save changes
        session.commit()

        # Prepare user notification based on status
        if hasattr(order, 'status') and order.status in ['shipped', 'delivered']:
            # Create status emoji
            status_emoji = '🚚' if order.status == 'shipped' else '📦'

            # Enhance the notification for shipping status
            if order.status == 'shipped':
                tracking_link = ""
                if order.tracking_number:
                    tracking_link = f"""
• <b>Track your package:</b>
  <a href="https://global.cainiao.com/detail.htm?mailNoList={order.tracking_number}">Click here to track</a>
"""

                notification = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   {status_emoji} <b>ORDER SHIPPED!</b> {status_emoji}  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Great news! Your order is on its way to you!

<b>📦 Order Details:</b>
• Order #: <code>{order.order_number}</code>
• Status: <b>SHIPPED</b>
• Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

{f"• Tracking #: <code>{order.tracking_number}</code>" if order.tracking_number else ""}
{tracking_link}

<b>Expected delivery:</b> 15-30 days

You can check your order status anytime using the
"🔍 Track Order" button.

<i>Thank you for shopping with AliPay_ETH!</i>
"""
            else:  # delivered
                notification = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   {status_emoji} <b>ORDER DELIVERED!</b> {status_emoji}  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your order has been marked as delivered!

<b>📦 Order Details:</b>
• Order #: <code>{order.order_number}</code>
• Status: <b>DELIVERED</b>
• Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}

We hope you enjoy your purchase!
Please let us know if you have any questions.

<i>Thank you for shopping with AliPay_ETH!</i>
"""

            # Send the notification to customer
            bot.send_message(
                customer.telegram_id,
                notification,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        else:
            # Simple update notification for other status changes
            bot.send_message(
                customer.telegram_id,
                f"""
<b>Order Update</b>

Your Order #{order.order_number} has been updated:
• Status: <b>{order.status.upper()}</b>
{f"• Tracking #: <code>{order.tracking_number}</code>" if hasattr(order, 'tracking_number') and order.tracking_number else ""}
{f"• Order ID: <code>{order.order_id}</code>" if hasattr(order, 'order_id') and order.order_id else ""}

Use 🔍 <b>Track Order</b> for the latest details.
""",
                parse_mode='HTML'
            )

        # Confirm to admin
        updates_list = []
        if 'status' in locals() and locals()['status']:
            updates_list.append(f"status: {order.status}")
        if order.tracking_number:
            updates_list.append(f"tracking: {order.tracking_number}")
        if order.order_id:
            updates_list.append(f"orderid: {order.order_id}")

        updates_text = ", ".join(updates_list)
        bot.reply_to(message, f"✅ Order #{order_number} updated successfully!\n\nUpdates: {updates_text}")

    except Exception as e:
        logger.error(f"Error updating order: {e}")
        logger.error(traceback.format_exc())
        bot.reply_to(message, "❌ Error updating order. Use /updateorder help for instructions.")
    finally:
        safe_close_session(session)

def check_subscription_status():
    """Check for users with expired subscriptions and notify them"""
    session = None
    try:
        session = get_session()
        now = datetime.utcnow()

        # Find users with expiring/expired subscriptions
        users = session.query(User).filter(
            User.subscription_date.isnot(None)  # Only check users with subscription dates
        ).all()

        for user in users:
            try:
                if not user.subscription_date:
                    continue

                days_passed = (now - user.subscription_date).days
                days_remaining = 30 - days_passed

                if days_remaining <= 3:  # Notify when 3 or fewer days remain
                    # Only send reminder if we haven't sent one in the last 24 hours
                    if (not user.last_subscription_reminder or 
                        (now - user.last_subscription_reminder).total_seconds() > 24 * 3600):

                        if days_remaining <= 0:
                            # Subscription expired
                            bot.send_message(
                                user.telegram_id,
                                """
SUBSCRIPTION

Your subscription has expired!

Expired: {-days_remaining} days ago
Renew now to continue using AliPay_ETH

Use the 💳 <b>Subscription</b> menu to renew.
""",
                                parse_mode='HTML'
                            )
                        else:
                            # Subscription expiring soon
                            bot.send_message(
                                user.telegram_id,
                                f"""
REMINDER

Subscription ending soon!

Days remaining: {days_remaining}
Renew now to avoid interruption

Use the 💳 <b>Subscription</b> menu to renew.
""",
                                parse_mode='HTML'
                            )

                        # Update last reminder time
                        user.last_subscription_reminder = now
                        session.commit()

            except Exception as e:
                logger.error(f"Error notifying user {user.telegram_id}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error checking subscriptions: {e}")
    finally:
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

def main():
    """Main function to start the bot with optimized performance"""
    logger.info("🚀 Starting bot in polling mode...")

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
        logger.info("Telebot connection optimizations applied")
    except Exception as optimization_error:
        logger.warning(f"Could not apply all performance optimizations: {optimization_error}")

    # Start polling with recovery
    while not shutdown_requested:
        try:
            logger.info("Starting polling...")
            bot.polling(none_stop=True, timeout=30, interval=0.25)  # More responsive polling
        except Exception as e:
            if shutdown_requested:
                break
            logger.error(f"Polling error: {e}")
            logger.info("Restarting in 3 seconds...")
            time.sleep(3)  # Quicker recovery

    logger.info("Bot shutdown complete")

if __name__ == "__main__":
    # Start the subscription checker in a separate thread
    subscription_thread = threading.Thread(target=run_subscription_checker)
    subscription_thread.daemon = True
    subscription_thread.start()
    main()

@bot.message_handler(func=lambda msg: msg.text == '📅 Subscription')
def check_subscription(message):
    """Check user's subscription status with enhanced visual appeal"""
    chat_id = message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(
                chat_id, 
                "✨ Please register first to access premium subscription features! ✨", 
                reply_markup=create_main_menu(is_registered=False)
            )
            return

        # Calculate subscription status
        now = datetime.utcnow()
        if user.subscription_date:
            days_passed = (now - user.subscription_date).days
            days_remaining = 30 - days_passed

            if days_remaining > 0:
                # Active subscription
                status_emoji = "✅"
                status = f"Active ({days_remaining} days remaining)"
                renew_date = (user.subscription_date + timedelta(days=30)).strftime('%Y-%m-%d')
                status_color = "green"
            else:
                # Expired subscription
                status_emoji = "⚠️"
                status = "Expired"
                renew_date = "Renewal needed"
                status_color = "red"

            # Create attractive subscription renewal buttons
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("💫 Renew 1 Month ($1) 💫", callback_data="renew_1")
            )
            markup.add(
                InlineKeyboardButton("🎁 View Premium Benefits", callback_data="sub_benefits")
            )

            # Enhanced fancy subscription message with better formatting
            subscription_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✨ <b>PREMIUM SUBSCRIPTION</b> ✨  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

{status_emoji} <b>Status:</b> <code>{status}</code>

📆 <b>Next renewal:</b> <code>{renew_date}</code>
💎 <b>Monthly fee:</b> <code>$1.00</code> (150 ETB)
👑 <b>Benefits:</b> Full access to all premium features

<b>Keep your subscription active to enjoy:</b>
• 🛍️ Unlimited AliExpress shopping
• 💰 Special discounts
• 🎯 Priority order processing
• 🌟 Premium customer support

<i>Click below to renew your membership!</i>
"""
            bot.send_message(chat_id, subscription_msg, parse_mode='HTML', reply_markup=markup)
        else:
            bot.send_message(
                chat_id, 
                "✨ No subscription information found. Please contact our support team for assistance. ✨",
                parse_mode='HTML'
            )
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        bot.send_message(
            chat_id, 
            "⚠️ <b>Oops!</b> We encountered a temporary glitch. Please try again in a moment. ⚠️",
            parse_mode='HTML'
        )
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data == "renew_1")
def handle_subscription_renewal(call):
    """Handle subscription renewal"""
    chat_id = call.message.chat.id
    session = None
    try:
        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()
        if not user:
            bot.answer_callback_query(call.id, "User not found.")
            return

        # Check if user has enough balance for subscription
        if user.balance < 1.0:
            bot.answer_callback_query(call.id, "Insufficient balance. Please deposit funds first.")
            bot.send_message(
                chat_id,
                """
❌ <b>Insufficient Balance</b>

You need at least $1.00 in your account to renew your subscription.
Please use the 💰 Deposit option to add funds.
""",
                parse_mode='HTML'
            )
            return

        # Deduct subscription fee and update date
        user.balance -= 1.0
        user.subscription_date = datetime.utcnow()
        user.last_subscription_reminder = None  # Reset reminder

        try:
            session.commit()
            bot.answer_callback_query(call.id, "Subscription renewed successfully!")
            bot.edit_message_text(
                f"""
✅ <b>Subscription Renewed!</b>

Your subscription has been renewed for 1 month.
New expiry date: {(user.subscription_date + timedelta(days=30)).strftime('%Y-%m-%d')}
Current balance: ${user.balance:.2f}

Thank you for using AliPay_ETH!
""",
                chat_id=chat_id,
                message_id=call.message.message_id,
                parse_mode='HTML'
            )
        except Exception as commit_error:
            logger.error(f"Error committing subscription renewal: {commit_error}")
            session.rollback()
            bot.answer_callback_query(call.id, "Database error, please try again.")
            return
    except Exception as e:
        logger.error(f"Error renewing subscription: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error renewing subscription.")
    finally:
        safe_close_session(session)

@bot.callback_query_handler(func=lambda call: call.data == "sub_benefits")
def handle_subscription_benefits(call):
    """Handle subscription benefits button"""
    try:
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
  Earn rewards for inviting friends

<i>All this for just $1/month!</i>
"""
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            benefits_msg,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error showing subscription benefits: {e}")
        bot.answer_callback_query(call.id, "Error showing benefits")

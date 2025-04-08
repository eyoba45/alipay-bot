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
• ETB: <code>150</code> birr

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
    """Process registration payment with Chapa integration"""
    chat_id = message.chat.id
    session = None

    try:
        if chat_id not in registration_data:
            logger.error(f"Missing registration data for user {chat_id}")
            bot.send_message(chat_id, "Registration data missing. Please restart registration with /start.")
            return

        # Import the Chapa payment module
        from chapa_payment import generate_registration_payment

        # Generate payment link
        payment_link = generate_registration_payment(registration_data[chat_id])

        if not payment_link or 'checkout_url' not in payment_link:
            # Fall back to error message
            bot.send_message(
                chat_id,
                "❌ Error generating payment link. Please try again or contact support.",
                parse_mode='HTML'
            )
            return

        # Send payment link with inline button
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💳 Pay Registration Fee", url=payment_link['checkout_url']))

        payment_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💫 <b>COMPLETE REGISTRATION</b> 💫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Click the button below to securely pay the registration fee:
• Amount: <code>150</code> birr
• Secure payment via Chapa
• Instant activation after payment

<b>Available Payment Methods:</b>
• TeleBirr
• CBE Birr
• HelloCash
• Amole
• Credit/Debit Cards

<i>Your account will be automatically activated after successful payment!</i>
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
                    logger.info(f"User {chat_id} already has a pending approval - auto-approving")
                    break
                break
            except Exception as db_error:
                logger.error(f"Database check error (attempt {db_attempt+1}): {db_error}")
                safe_close_session(session)
                if db_attempt == 2:  # Last attempt failed
                    raise
                time.sleep(0.5 * (db_attempt + 1))  # Progressive delay

        # AUTO-APPROVE: Instead of adding to pending, create user directly
        max_retries = 5
        for retry_count in range(max_retries):
            try:
                # Always get a fresh session for each retry
                if session:
                    safe_close_session(session)
                session = get_session()

                # Check if there's an existing pending approval
                existing_pending = session.query(PendingApproval).filter_by(telegram_id=chat_id).first()

                # If not, create a new user directly (auto-approve)
                if not existing_pending:
                    # Create new user
                    new_user = User(
                        telegram_id=chat_id,
                        name=registration_data[chat_id]['name'],
                        phone=registration_data[chat_id]['phone'],
                        address=registration_data[chat_id]['address'],
                        balance=0.0,
                        subscription_date=datetime.utcnow()
                    )
                    session.add(new_user)
                    session.commit()
                    logger.info(f"Auto-approved and registered user {chat_id}")
                else:
                    # Convert pending approval to full user
                    new_user = User(
                        telegram_id=chat_id,
                        name=existing_pending.name,
                        phone=existing_pending.phone,
                        address=existing_pending.address,
                        balance=0.0,
                        subscription_date=datetime.utcnow()
                    )
                    session.add(new_user)
                    session.delete(existing_pending)
                    session.commit()
                    logger.info(f"Converted pending approval to full user for {chat_id}")

                # Send notification to admin
                if ADMIN_ID:
                    admin_msg = f"""
✅ <b>AUTO-APPROVED REGISTRATION</b>

User Information:
Name: <b>{registration_data[chat_id]['name']}</b>
Address: {registration_data[chat_id]['address']}
Phone: <code>{registration_data[chat_id]['phone']}</code>
ID: <code>{chat_id}</code>

Registration Fee: 150 ETB
Payment screenshot attached below
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

User has been automatically registered.
"""
                    try:
                        bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')
                        bot.send_photo(ADMIN_ID, file_id, caption="📸 Auto-approved Registration Payment")
                    except Exception as admin_error:
                        logger.error(f"Error notifying admin about auto-approval: {admin_error}")

                break
            except Exception as db_error:
                logger.error(f"Database error (attempt {retry_count+1}/{max_retries}): {db_error}")
                logger.error(traceback.format_exc())
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

        logger.info(f"Auto-approval confirmation sent to user {chat_id}")
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
• Pay the 150 birr registration fee

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
        payment_details(message, amount)  # Call the payment_details function directly

def send_payment_details(message, amount):
    """Send payment details to user"""
    payment_details(message, amount)  # Call the existing payment_details function

def payment_details(message, amount):
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
•Amole
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
    """Process deposit screenshot with auto-approval"""
    chat_id = message.chat.id
    session = None
    try:
        file_id = message.photo[-1].file_id
        deposit_amount = user_states[chat_id].get('deposit_amount', 0)
        birr_amount = int(deposit_amount * 160)

        session = get_session()
        user = session.query(User).filter_by(telegram_id=chat_id).first()

        if not user:
            bot.send_message(chat_id, "Please register first before making a deposit.")
            return

        # Check if this is for subscription renewal
        is_for_subscription = False
        if isinstance(user_states[chat_id], dict) and user_states[chat_id].get('for_subscription'):
            is_for_subscription = True
            
        # Check if user has a subscription date and if it needs renewal
        now = datetime.utcnow()
        subscription_updated = False
        subscription_renewal_msg = ""
        
        if is_for_subscription or (user.subscription_date and (now - user.subscription_date).days >= 30):
            # Determine if we should deduct subscription fee
            if deposit_amount >= 1.0:  # Only if deposit is at least $1
                user.balance += (deposit_amount - 1.0)  # Add amount after subscription fee
                user.subscription_date = now  # Reset subscription date
                subscription_updated = True
                
                if user.subscription_date:
                    subscription_renewal_msg = f"\n<b>📅 SUBSCRIPTION RENEWED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                else:
                    subscription_renewal_msg = f"\n<b>📅 SUBSCRIPTION ACTIVATED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• Expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                
                logger.info(f"Subscription {'renewed' if user.subscription_date else 'activated'} for user {chat_id}")
            else:
                # Deposit too small for subscription, just add to balance
                user.balance += deposit_amount
                logger.info(f"Deposit amount ${deposit_amount} too small for subscription renewal")
        else:
            # Regular deposit, just add to balance
            user.balance += deposit_amount

        # Create approved deposit record
        pending_deposit = PendingDeposit(
            user_id=user.id,
            amount=deposit_amount,
            status='Approved'  # Set as approved immediately
        )
        session.add(pending_deposit)
        session.commit()

        logger.info(f"Auto-approved deposit of ${deposit_amount} for user {chat_id}")

        # Notify admin about auto-approved deposit
        admin_msg = f"""
✅ <b>AUTO-APPROVED DEPOSIT</b>

User Details:
Name: <b>{user.name}</b>
ID: <code>{chat_id}</code>
Phone: <code>{user.phone}</code>

Amount:
USD: <code>${deposit_amount:,.2f}</code>
ETB: <code>{birr_amount:,}</code>

New Balance: <code>${user.balance:.2f}</code>

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Screenshot attached below
"""
        if ADMIN_ID:
            try:
                bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML')
                bot.send_photo(ADMIN_ID, file_id, caption="📸 Auto-approved Deposit Screenshot")
            except Exception as admin_error:
                logger.error(f"Error notifying admin about auto-approval: {admin_error}")

        # Send enhanced fancy confirmation to user
        # Check if we need to add subscription information to the message
        deposit_msg = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${deposit_amount:.2f}
{f"• Amount after subscription fee: ${deposit_amount - 1.0:.2f}" if subscription_updated else ""}
{subscription_renewal_msg}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
"""
        
        bot.send_message(
            chat_id,
            deposit_msg,
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
            # Default to 0 if balance is None
            balance = user.balance if user.balance is not None else 0
            birr_balance = int(balance * 160)
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>YOUR BALANCE</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Available:</b> <code>{birr_balance:,}</code> birr
≈ $<code>{balance:,.2f}</code> USD

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
<a href="{link}">{link}</a>

<b>⏰ TIME:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

<i>Please review and process this order</i>
"""
        if ADMIN_ID:
            bot.send_message(ADMIN_ID, admin_msg, parse_mode='HTML', reply_markup=admin_markup)

        # Calculate remaining balance
        remaining_balance = user.balance
        birr_balance = int(remaining_balance * 160)  # Convert to birr

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
            # Check subscription status to see if we need to deduct the subscription fee
            now = datetime.utcnow()
            subscription_deducted = False
            subscription_renewal_msg = ""
            
            if user.subscription_date:
                days_passed = (now - user.subscription_date).days
                # If subscription has expired, deduct $1 for renewal
                if days_passed >= 30:
                    # Only deduct if they have enough to cover deposit + subscription
                    if amount >= 1.0:
                        amount_after_sub = amount - 1.0  # Deduct $1 subscription fee
                        user.balance += amount_after_sub
                        user.subscription_date = now  # Set new subscription date
                        subscription_deducted = True
                        subscription_renewal_msg = "\n<b>📅 SUBSCRIPTION RENEWED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: " + (now + timedelta(days=30)).strftime('%Y-%m-%d')
                    else:
                        # If deposit is less than $1, just add to balance without renewing
                        user.balance += amount
                else:
                    # Subscription still active, add full amount
                    user.balance += amount
            else:
                # No previous subscription, set initial subscription date and deduct fee
                if amount >= 1.0:
                    amount_after_sub = amount - 1.0  # Deduct $1 subscription fee
                    user.balance += amount_after_sub
                    user.subscription_date = now  # Set initial subscription date
                    subscription_deducted = True
                    subscription_renewal_msg = "\n<b>📅 SUBSCRIPTION ACTIVATED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• Expiry date: " + (now + timedelta(days=30)).strftime('%Y-%m-%d')
                else:
                    # If deposit is less than $1, just add to balance without subscription
                    user.balance += amount
            
            pending_deposit.status = 'Approved'
            session.commit()

            # Notify user
            message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{int(amount * 160):,}</code> birr
• USD Value: ${amount:.2f}
{f"• Amount after subscription fee: ${amount - 1.0:.2f}" if subscription_deducted else ""}
{subscription_renewal_msg}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
"""
            
            bot.send_message(
                chat_id,
                message_text,
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

@bot.message_handler(func=lambda msg: msg.text == '🔍 Track Order')
def track_order(message):
    """Handle track order button with enhanced UI and options"""
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
            
        # Ask for order number
        msg = """
📦 <b>TRACK YOUR ORDER</b>

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
    """Process order number for tracking"""
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
        if order.status == "Completed":
            status_emoji = "✅"
        elif order.status == "Cancelled":
            status_emoji = "❌"
        elif order.status == "Processing":
            status_emoji = "🔄"
        elif order.status == "Shipped":
            status_emoji = "🚚"
        
        # Create tracking link if tracking number exists
        tracking_info = ""
        if order.tracking_number:
            tracking_link = f"https://t.17track.net/en#nums={order.tracking_number}"
            tracking_info = f"""
<b>Tracking Number:</b> <code>{order.tracking_number}</code>
<a href="{tracking_link}">Track Package on 17Track</a>
"""
            
        # Create order message
        order_msg = f"""
📦 <b>ORDER DETAILS</b>

<b>Order Number:</b> #{order.order_number}
<b>Status:</b> {status_emoji} {order.status}
<b>Amount:</b> ${order.amount:.2f}
<b>Date:</b> {order.created_at.strftime('%Y-%m-%d')}
{tracking_info}
"""
        
        if order.order_id:
            order_msg += f"<b>AliExpress ID:</b> <code>{order.order_id}</code>\n"
            
        if order.product_link:
            order_msg += f"""
<b>Product Link:</b>
<a href="{order.product_link}">View Product on AliExpress</a>
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
def order_status(message):
    """Handle order status button with improved tracking"""
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
            
        # Show all orders
        orders_text = """
📊 <b>YOUR ORDERS</b>

Here are your recent orders:
"""
        for order in orders:
            status_emoji = "⏳"
            if order.status == "Completed":
                status_emoji = "✅"
            elif order.status == "Cancelled":
                status_emoji = "❌"
            elif order.status == "Processing":
                status_emoji = "🔄"
            elif order.status == "Shipped":
                status_emoji = "🚚"
                
            # Format order details
            order_details = f"""
<b>Order #{order.order_number}</b>
Status: {status_emoji} <b>{order.status}</b>
Amount: ${order.amount:.2f}
Date: {order.created_at.strftime('%Y-%m-%d')}
"""
            if order.tracking_number:
                order_details += f"Tracking: <code>{order.tracking_number}</code>\n"
                
            if order.order_id:
                order_details += f"AliExpress ID: <code>{order.order_id}</code>\n"
                
            orders_text += order_details
            
        orders_text += """
Use 🔍 <b>Track Order</b> to get detailed tracking information for a specific order.
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

@bot.callback_query_handler(func=lambda call: call.data.startswith(('process_order_', 'reject_order_')))
def handle_order_admin_decision(call):
    """Handle admin approval/rejection for orders with enhanced user notifications"""
    session = None
    try:
        parts = call.data.split('_order_')
        action = parts[0]
        order_id = int(parts[1])

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

        # Update order with the details
        order.order_id = aliexpress_id
        order.tracking_number = tracking if tracking else None
        order.amount = price
        order.status = "Shipped" if tracking else "Processing"
        order.updated_at = datetime.utcnow()
        session.commit()

        # Notify user
        bot.send_message(
            user_telegram_id,
            f"""
📦 <b>ORDER UPDATE</b>

Your order #{order.order_number} has been {order.status.lower()}!

<b>Details:</b>
• Status: {"🚚" if order.status == "Shipped" else "🔄"} <b>{order.status}</b>
• AliExpress Order ID: <code>{aliexpress_id}</code>
• Amount: ${price:.2f}
{f"• Tracking Number: <code>{tracking}</code>" if tracking else ""}

{f'<a href="https://t.17track.net/en#nums={tracking}">Track your package</a>' if tracking else "Your tracking information will be added soon."}

Thank you for your order!
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

                if user.last_subscription_reminder:
                    days_since_last_reminder = (now - user.last_subscription_reminder).days
                    if days_since_last_reminder >= 3:  # Don't spam users, minimum 3 days between reminders
                        should_remind = True
                else:
                    should_remind = True
                
                if should_remind:
                    # Case 1: Subscription is about to expire (5 days or less remaining)
                    if 0 < days_remaining <= 5:
                        renewal_markup = InlineKeyboardMarkup()
                        renewal_markup.add(InlineKeyboardButton("💰 Deposit to Renew", callback_data="deposit_renew"))
                        renewal_markup.add(InlineKeyboardButton("📋 Subscription Benefits", callback_data="sub_benefits"))
                        
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ⚠️ <b>SUBSCRIPTION REMINDER</b> ⚠️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription will expire in <b>{days_remaining} days</b>.

To maintain uninterrupted access to our services, please make a deposit of at least $1 (150 birr) before your subscription expires.

<i>Note: Your next deposit will automatically renew your subscription for another month.</i>
""",
                            parse_mode='HTML',
                            reply_markup=renewal_markup
                        )
                        logger.info(f"Sent subscription expiry reminder to user {user.telegram_id}, {days_remaining} days remaining")
                    
                    # Case 2: Subscription has expired
                    elif days_remaining <= 0:
                        renewal_markup = InlineKeyboardMarkup()
                        renewal_markup.add(InlineKeyboardButton("💰 Renew Now", callback_data="deposit_renew"))
                        
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚫 <b>SUBSCRIPTION EXPIRED</b> 🚫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has expired. It's been {abs(days_remaining)} days since your subscription ended.

To continue using our services, please make a deposit of at least $1 (150 birr) to automatically renew your subscription.

<i>Your account features may be limited until you renew your subscription.</i>
""",
                            parse_mode='HTML',
                            reply_markup=renewal_markup
                        )
                        logger.info(f"Sent subscription expired notification to user {user.telegram_id}, expired {abs(days_remaining)} days ago")

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

def check_subscription_status():
    """Check subscription status for all users and send reminders"""
    session = None
    try:
        session = get_session()
        users = session.query(User).all()
        now = datetime.utcnow()
        logger.info(f"Checking subscription status for {len(users)} users")
        
        for user in users:
            try:
                # Skip users without subscription date (never subscribed)
                if not user.subscription_date:
                    continue
                
                # Calculate days remaining in subscription
                days_passed = (now - user.subscription_date).days
                days_remaining = 30 - days_passed
                
                # Determine if we should send a reminder
                should_remind = False
                
                # Check when the last reminder was sent
                if user.last_subscription_reminder:
                    days_since_last_reminder = (now - user.last_subscription_reminder).days
                    if days_since_last_reminder >= 3:  # Don't spam users, minimum 3 days between reminders
                        should_remind = True
                else:
                    should_remind = True
                
                if should_remind:
                    # Case 1: Subscription is about to expire (5 days or less remaining)
                    if 0 < days_remaining <= 5:
                        renewal_markup = InlineKeyboardMarkup()
                        renewal_markup.add(InlineKeyboardButton("💰 Deposit to Renew", callback_data="deposit_renew"))
                        renewal_markup.add(InlineKeyboardButton("📋 Subscription Benefits", callback_data="sub_benefits"))
                        
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ⚠️ <b>SUBSCRIPTION REMINDER</b> ⚠️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription will expire in <b>{days_remaining} days</b>.

To maintain uninterrupted access to our services, please make a deposit of at least $1 (150 birr) before your subscription expires.

<i>Note: Your next deposit will automatically renew your subscription for another month.</i>
""",
                            parse_mode='HTML',
                            reply_markup=renewal_markup
                        )
                        logger.info(f"Sent subscription expiry reminder to user {user.telegram_id}, {days_remaining} days remaining")
                    
                    # Case 2: Subscription has expired
                    elif days_remaining <= 0:
                        renewal_markup = InlineKeyboardMarkup()
                        renewal_markup.add(InlineKeyboardButton("💰 Renew Now", callback_data="deposit_renew"))
                        
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚫 <b>SUBSCRIPTION EXPIRED</b> 🚫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has expired. It's been {abs(days_remaining)} days since your subscription ended.

To continue using our services, please make a deposit of at least $1 (150 birr) to automatically renew your subscription.

<i>Your account features may be limited until you renew your subscription.</i>
""",
                            parse_mode='HTML',
                            reply_markup=renewal_markup
                        )
                        logger.info(f"Sent subscription expired notification to user {user.telegram_id}, expired {abs(days_remaining)} days ago")
                
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


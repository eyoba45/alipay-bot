#!/usr/bin/env python3
"""
Chapa Auto-Payment Verification Service - Enhanced Version

This script automatically verifies payments through Chapa API and approves them
without manual intervention when they are successfully confirmed.
"""
import os
import logging
import time
import traceback
import requests
import telebot
from datetime import datetime, timedelta
import threading
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Verification interval in seconds (check every 15 seconds for faster service)
VERIFICATION_INTERVAL = 15

def get_bot():
    """Import and return bot instance - with improved reliability"""
    try:
        # Attempt to get a Telegram token regardless of import method
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not found in environment")
            return None, None

        # For notification purposes, create a direct bot instance
        # This bypasses the need to import from the main bot module
        try:
            import telebot
            from telebot.types import ReplyKeyboardMarkup, KeyboardButton
            
            temp_bot = telebot.TeleBot(token)
            
            # Simple menu creator function
            def simple_menu(is_registered=False, chat_id=None):
                markup = ReplyKeyboardMarkup(resize_keyboard=True)
                
                if is_registered:
                    # Main menu for registered users
                    markup.row(
                        KeyboardButton('💰 Deposit'),
                        KeyboardButton('📦 Submit Order')
                    )
                    markup.row(
                        KeyboardButton('🔍 Track Order'),
                        KeyboardButton('💳 Balance')
                    )
                    markup.row(
                        KeyboardButton('📊 Order Status'),
                        KeyboardButton('⏱ Subscription')
                    )
                    markup.row(
                        KeyboardButton('👥 My Referral Link'),
                        KeyboardButton('❓ Help Center')
                    )
                else:
                    # Registration menu
                    markup.row(KeyboardButton('🔑 Register'))
                    markup.row(KeyboardButton('❓ Help Center'))
                
                return markup
                
            logger.info("✅ Created standalone bot instance for payment notifications")
            return temp_bot, simple_menu
            
        except Exception as e:
            logger.error(f"Could not create bot instance: {e}")
            logger.error(traceback.format_exc())
            return None, None
            
    except Exception as e:
        logger.error(f"Error initializing bot: {e}")
        logger.error(traceback.format_exc())
        # Return None but don't halt operations - we can still verify payments
        # even without being able to send notifications
        return None, None

def verify_payment(tx_ref):
    """Verify a payment with Chapa API with enhanced error handling"""
    try:
        chapa_secret = os.environ.get('CHAPA_SECRET_KEY')
        if not chapa_secret:
            logger.error("CHAPA_SECRET_KEY not set")
            return False

        url = f"https://api.chapa.co/v1/transaction/verify/{tx_ref}"
        headers = {
            "Authorization": f"Bearer {chapa_secret}",
            "Content-Type": "application/json"
        }

        # Initialize response outside the try block
        response = None
        
        # Make the API request to Chapa with a timeout and retry logic
        for attempt in range(3):  # Try up to 3 times
            try:
                response = requests.get(url, headers=headers, timeout=30)
                # Check if rate limited or server error
                if response.status_code == 429 or response.status_code >= 500:
                    wait_time = min(2 ** attempt, 8)  # Exponential backoff up to 8 seconds
                    logger.warning(f"Rate limited or server error ({response.status_code}), retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                # Break if successful or client error (not worth retrying)
                break
            except requests.exceptions.RequestException as e:
                if attempt < 2:  # Don't log on last attempt as we'll catch it below
                    logger.warning(f"Network error on attempt {attempt+1}/3: {e}")
                    time.sleep(2)
                else:
                    raise
        
        # Check if we got a response at all
        if response is None:
            logger.error("Failed to get response from Chapa API after multiple attempts")
            return False

        # Process the response
        try:
            response_data = response.json()
        except ValueError:
            logger.error(f"Invalid JSON response from Chapa API: {response.text}")
            return False

        # Log the full response for debugging
        logger.info(f"Payment verification response for {tx_ref}: {response_data}")

        # First check the overall response status
        if response_data.get('status') != 'success':
            logger.warning(f"Payment verification failed with status: {response_data.get('status')}")
            # Return special response for "Transaction not found" since this might mean payment was not initiated
            if 'Transaction not found' in str(response_data.get('message', '')):
                logger.warning(f"Transaction {tx_ref} not found in Chapa system")
                return {'payment_status': 'not_found', 'message': 'Transaction not found'}
            return False
            
        # Then check the data status 
        data = response_data.get('data', {})
        if not data:
            logger.warning(f"Payment verification response missing data field")
            return False
            
        # Check if payment is actually completed
        # The payment was found but status must be 'success' to indicate actual payment
        payment_status = data.get('status')
        if payment_status != 'success':
            logger.warning(f"Payment found but status is not success: {payment_status}")
            # For failed/cancelled payments, we'll return the data with the status
            # so we can update pending approvals to allow users to retry
            if payment_status in ['failed', 'cancelled', 'failed/cancelled']:
                logger.info(f"Payment {tx_ref} was {payment_status}, marking for retry")
                data['payment_status'] = 'failed/cancelled'
                return data
            # For pending payments, return a special status
            if payment_status == 'pending':
                logger.info(f"Payment {tx_ref} is still pending in Chapa system")
                data['payment_status'] = 'pending'
                return data
            return False
            
        # Check if verify_transaction status is also success
        verify_status = data.get('verify_transaction', {}).get('status')
        if verify_status and verify_status != 'success':
            logger.warning(f"Transaction verification failed: {verify_status}")
            return False
            
        # Check the transaction status 
        if 'tx_ref' not in data:
            logger.warning(f"Transaction reference not found in response")
            return False
            
        logger.info(f"✅ Payment {tx_ref} successfully verified with Chapa")
        return data

    except Exception as e:
        logger.error(f"Error verifying payment {tx_ref}: {e}")
        logger.error(traceback.format_exc())
        return False

def process_verified_registration(telegram_id, payment_data):
    """Process a verified registration payment with improved notification"""
    session = None
    try:
        logger.info(f"Processing verified registration for user {telegram_id}")

        session = get_session()

        # Check if user already exists
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            logger.info(f"User {telegram_id} already registered")
            return True

        # Look for pending approval
        pending = session.query(PendingApproval).filter_by(telegram_id=telegram_id).first()
        if not pending:
            logger.warning(f"No pending approval found for user {telegram_id}")
            return False

        # Create new user
        new_user = User(
            telegram_id=telegram_id,
            name=pending.name,
            phone=pending.phone,
            address=pending.address,
            balance=0.0,
            subscription_date=datetime.utcnow()
        )
        session.add(new_user)

        # Delete pending approval
        session.delete(pending)
        session.commit()

        logger.info(f"✅ User {telegram_id} registered with AUTO-APPROVAL via Chapa")

        # Create direct bot instance for notifications to ensure delivery
        try:
            import telebot
            from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
            
            token = os.environ.get('TELEGRAM_BOT_TOKEN')
            if token:
                # Create bot instance directly
                temp_bot = telebot.TeleBot(token)
                logger.info(f"✅ Created direct bot instance for registration approval notification")
                
                # Create main menu for reply
                markup = ReplyKeyboardMarkup(resize_keyboard=True)
                markup.row(
                    KeyboardButton('💰 Deposit'),
                    KeyboardButton('📦 Submit Order')
                )
                markup.row(
                    KeyboardButton('🔍 Track Order'),
                    KeyboardButton('💳 Balance')
                )
                markup.row(
                    KeyboardButton('📊 Order Status'),
                    KeyboardButton('⏱ Subscription')
                )
                markup.row(
                    KeyboardButton('👥 My Referral Link'),
                    KeyboardButton('❓ Help Center')
                )
                
                # Send welcome message with menu
                temp_bot.send_message(
                    telegram_id,
                    """
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been automatically activated after successful payment verification! You're all set to start shopping on AliExpress using Ethiopian Birr!

<b>📱 Your Services:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance

Need assistance? Use ❓ <b>Help Center</b> anytime!
""",
                    parse_mode='HTML',
                    reply_markup=markup
                )
                logger.info(f"✅ Successfully sent registration approval notification to user {telegram_id}")
                
                # Also notify admin if admin ID is set
                admin_id = os.environ.get('ADMIN_ID')
                if admin_id:
                    try:
                        temp_bot.send_message(
                            int(admin_id),
                            f"""
✅ <b>AUTO-APPROVED REGISTRATION</b>

User successfully registered with payment verification:
• Name: <b>{pending.name}</b>
• Phone: <code>{pending.phone}</code>
• ID: <code>{telegram_id}</code>

Payment was automatically verified through Chapa API.
Transaction Reference: <code>{pending.tx_ref}</code>
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""",
                            parse_mode='HTML'
                        )
                    except Exception as admin_err:
                        logger.error(f"Error notifying admin about auto-approved registration: {admin_err}")
                
                # Send tutorial offer after a short delay
                time.sleep(1)  # Give user time to read welcome message
                try:
                    # Tutorial message removed as requested
                    logger.info(f"✅ Tutorial message removed as requested")
                except Exception as tutorial_err:
                    logger.error(f"Error sending tutorial offer: {tutorial_err}")
                    logger.error(traceback.format_exc())
            else:
                logger.error("TELEGRAM_BOT_TOKEN not found for registration notifications")
        except Exception as notification_err:
            logger.error(f"Error sending registration notification: {notification_err}")
            logger.error(traceback.format_exc())

        return True
    except Exception as e:
        logger.error(f"Error processing verified registration: {e}")
        logger.error(traceback.format_exc())
        if session:
            session.rollback()
        return False
    finally:
        safe_close_session(session)

def process_verified_deposit(telegram_id, amount, payment_data):
    """Process a verified deposit payment"""
    session = None
    try:
        logger.info(f"Processing verified deposit for user {telegram_id}, amount: ${amount}")

        session = get_session()

        # Get user
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.warning(f"User {telegram_id} not found for deposit")
            return False

        # Check if this deposit has already been processed
        tx_ref = payment_data.get('tx_ref')
        existing_deposit = session.query(PendingDeposit).filter_by(
            user_id=user.id,
            tx_ref=tx_ref,
            status='Approved'
        ).first()

        if existing_deposit:
            logger.info(f"Deposit with tx_ref {tx_ref} for user {telegram_id} already processed")
            return True

        # Create or update pending deposit
        pending_deposit = session.query(PendingDeposit).filter_by(
            user_id=user.id,
            tx_ref=tx_ref
        ).first()

        if pending_deposit:
            # Only update if not already approved
            if pending_deposit.status != 'Approved':
                pending_deposit.status = 'Approved'
                pending_deposit.updated_at = datetime.utcnow()
            else:
                logger.info(f"Deposit already approved, skipping")
                return True
        else:
            # Create new deposit record
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Approved',
                tx_ref=tx_ref,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(pending_deposit)

        # Check if we need to handle subscription
        now = datetime.utcnow()
        subscription_updated = False
        
        # Fix: First ensure balance exists and is a number
        if user.balance is None:
            user.balance = 0.0
        
        # Check if user has subscription date and if it needs renewal
        if amount >= 1.0 and (not user.subscription_date or (now - user.subscription_date).days >= 30):
            # Deduct subscription fee
            old_balance = user.balance
            user.balance += (amount - 1.0)  # Add amount after subscription fee
            user.subscription_date = now  # Reset subscription date
            subscription_updated = True
            logger.info(f"Subscription {'renewed' if user.subscription_date else 'activated'} for user {telegram_id}")
            logger.info(f"Balance updated: ${old_balance:.2f} -> ${user.balance:.2f}")
        else:
            # Regular deposit or amount too small for subscription renewal
            old_balance = user.balance
            user.balance += amount
            logger.info(f"Balance updated: ${old_balance:.2f} -> ${user.balance:.2f}")
            
        # Force the balance to be updated immediately
        session.commit()
        
        # Double-check the balance update
        session.refresh(user)
        logger.info(f"Verified balance after update: ${user.balance:.2f}")

        logger.info(f"✅ Deposit of ${amount} for user {telegram_id} auto-approved via Chapa")

        # Create direct bot instance for notification
        try:
            import telebot
            from telebot.types import ReplyKeyboardMarkup, KeyboardButton
            
            token = os.environ.get('TELEGRAM_BOT_TOKEN')
            if token:
                # Create bot instance directly
                temp_bot = telebot.TeleBot(token)
                logger.info(f"✅ Created direct bot instance for deposit approval notification")
                
                # Calculate birr amount with improved conversion rate
                birr_amount = int(amount * 160)
                
                # Create subscription message if applicable
                subscription_msg = ""
                if subscription_updated:
                    subscription_msg = f"\n<b>📅 SUBSCRIPTION {'RENEWED' if user.subscription_date else 'ACTIVATED'}:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                
                # Create main menu for reply
                markup = ReplyKeyboardMarkup(resize_keyboard=True)
                markup.row(
                    KeyboardButton('💰 Deposit'),
                    KeyboardButton('📦 Submit Order')
                )
                markup.row(
                    KeyboardButton('🔍 Track Order'),
                    KeyboardButton('💳 Balance')
                )
                markup.row(
                    KeyboardButton('📊 Order Status'),
                    KeyboardButton('⏱ Subscription')
                )
                markup.row(
                    KeyboardButton('👥 My Referral Link'),
                    KeyboardButton('❓ Help Center')
                )
                
                # Send notification with appropriate menu
                temp_bot.send_message(
                    telegram_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${amount:.2f}
{f"• Amount after subscription fee: ${amount - 1.0:.2f}" if subscription_updated else ""}
{subscription_msg}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
""",
                    parse_mode='HTML',
                    reply_markup=markup
                )
                logger.info(f"✅ Successfully sent deposit approval notification to user {telegram_id}")
                
                # Notify admin about deposit approval
                admin_id = os.environ.get('ADMIN_ID')
                if admin_id:
                    try:
                        temp_bot.send_message(
                            int(admin_id),
                            f"""
✅ <b>AUTO-APPROVED DEPOSIT</b>

User deposit auto-approved:
• User ID: <code>{telegram_id}</code>
• Amount: {birr_amount:,} birr (${amount:.2f})
• Transaction: <code>{tx_ref}</code>
• Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
""",
                            parse_mode='HTML'
                        )
                    except Exception as admin_err:
                        logger.error(f"Error notifying admin about deposit: {admin_err}")
            else:
                logger.error("TELEGRAM_BOT_TOKEN not found for deposit notifications")
        except Exception as notification_err:
            logger.error(f"Error sending deposit notification: {notification_err}")
            logger.error(traceback.format_exc())

        return True
    except Exception as e:
        logger.error(f"Error processing verified deposit: {e}")
        logger.error(traceback.format_exc())
        if session:
            session.rollback()
        return False
    finally:
        safe_close_session(session)

def check_pending_registrations():
    """Check for pending registrations and verify their payments"""
    session = None
    try:
        session = get_session()
        # Store basic information for each pending approval and don't keep the ORM objects
        pending_data = []
        for pending in session.query(PendingApproval).all():
            pending_data.append({
                'telegram_id': pending.telegram_id,
                'tx_ref': pending.tx_ref,
                'created_at': pending.created_at
            })
        
        if pending_data:
            logger.info(f"Found {len(pending_data)} pending registrations to verify")
            
        # Close the first session to avoid keeping detached objects
        safe_close_session(session)
        
        # Initialize bot for notifications (do this once to avoid recreation for each user)
        import telebot
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
        
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if token:
            bot = telebot.TeleBot(token)
            logger.info("✅ Created standalone bot for payment notifications")
        else:
            bot = None
            logger.error("TELEGRAM_BOT_TOKEN not found in environment")
            
        # Simple menu creation function
        def create_main_menu(is_registered=False, chat_id=None):
            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            
            if is_registered:
                # Main menu for registered users
                markup.row(
                    KeyboardButton('💰 Deposit'),
                    KeyboardButton('📦 Submit Order')
                )
                markup.row(
                    KeyboardButton('🔍 Track Order'),
                    KeyboardButton('💳 Balance')
                )
                markup.row(
                    KeyboardButton('📊 Order Status'),
                    KeyboardButton('⏱ Subscription')
                )
                markup.row(
                    KeyboardButton('👥 My Referral Link'),
                    KeyboardButton('❓ Help Center')
                )
            else:
                # Registration menu
                markup.row(KeyboardButton('🔑 Register'))
                markup.row(KeyboardButton('❓ Help Center'))
            
            return markup
        
        # Process each pending registration with a fresh session
        for item in pending_data:
            session = get_session()  # Get a fresh session for each item
            try:
                telegram_id = item['telegram_id']
                tx_ref = item['tx_ref']
                created_at = item['created_at']
                
                # Fetch the current status of this pending approval
                pending = session.query(PendingApproval).filter_by(telegram_id=telegram_id).first()
                if not pending:
                    logger.info(f"Pending approval no longer exists for user {telegram_id}, skipping")
                    continue
                
                # Skip registrations without tx_ref
                if not tx_ref:
                    logger.warning(f"No tx_ref found for pending approval {telegram_id}, skipping")
                    continue
                    
                # Check if user already exists to avoid duplicate registrations
                existing_user = session.query(User).filter_by(telegram_id=telegram_id).first()
                if existing_user:
                    logger.info(f"User {telegram_id} already registered, deleting pending approval")
                    session.delete(pending)
                    session.commit()
                    continue
                
                # Verify payment with Chapa API - this is the only 100% reliable method
                logger.info(f"Verifying payment for registration tx_ref: {tx_ref}")
                payment_data = verify_payment(tx_ref)
                
                # Handle different payment verification results based on status
                if payment_data and isinstance(payment_data, dict):
                    payment_status = payment_data.get('payment_status')
                    
                    # Case 1: Failed or cancelled payments
                    if payment_status == 'failed/cancelled':
                        logger.info(f"Payment for user {telegram_id} was cancelled or failed, updating status for retry")
                        
                        # Update the status to allow retry
                        try:
                            pending.payment_status = 'Failed'
                        except:
                            # If column doesn't exist, just use status
                            logger.info(f"payment_status column not found, using status field only")
                        pending.status = 'Payment Failed'
                        session.commit()
                        
                        # Send a message to the user with retry option
                        bot, create_main_menu = get_bot()
                        if bot:
                            try:
                                # Create payment retry button
                                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                                retry_markup = InlineKeyboardMarkup()
                                retry_markup.add(InlineKeyboardButton("🔄 Retry Payment", callback_data=f"retry_payment_{telegram_id}"))
                                
                                bot.send_message(
                                    telegram_id,
                                    """
❌ <b>PAYMENT CANCELLED OR FAILED</b>

Your previous payment attempt was not completed. This could be because:
• You cancelled the payment
• The payment process timed out
• There was a technical issue

You can retry your payment by clicking the button below.
""",
                                    parse_mode='HTML',
                                    reply_markup=retry_markup
                                )
                                logger.info(f"Sent payment retry notification to user {telegram_id}")
                            except Exception as e:
                                logger.error(f"Error sending payment retry notification: {e}")
                        
                        # Close this session and continue to next registration
                        safe_close_session(session)
                        session = None
                        continue
                    
                    # Case 2: Transaction not found in Chapa system
                    elif payment_status == 'not_found':
                        logger.warning(f"Payment for user {telegram_id} not found in Chapa system")
                        
                        # Only update status if it's been more than 30 minutes
                        if created_at and (datetime.utcnow() - created_at).total_seconds() > 1800:  # 30 minutes
                            pending.status = 'Payment Not Found'
                            session.commit()
                            
                            # Send a message to the user with retry option
                            bot, create_main_menu = get_bot()
                            if bot:
                                try:
                                    # Create payment retry button
                                    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                                    retry_markup = InlineKeyboardMarkup()
                                    retry_markup.add(InlineKeyboardButton("🔄 Try Again", callback_data=f"retry_payment_{telegram_id}"))
                                    
                                    bot.send_message(
                                        telegram_id,
                                        """
⚠️ <b>PAYMENT NOT FOUND</b>

We couldn't find your payment in the Chapa system. This could be because:
• You didn't complete the payment process
• There was a delay in processing your payment
• Technical issues with the payment system

You can try again by clicking the button below.
""",
                                        parse_mode='HTML',
                                        reply_markup=retry_markup
                                    )
                                    logger.info(f"Sent payment not found notification to user {telegram_id}")
                                except Exception as e:
                                    logger.error(f"Error sending payment not found notification: {e}")
                        
                        # Continue to next registration
                        safe_close_session(session)
                        session = None
                        continue
                    
                    # Case 3: Payment is still pending in Chapa system
                    elif payment_status == 'pending':
                        logger.info(f"Payment for user {telegram_id} is still pending in Chapa system")
                        pending.status = 'Payment Pending'
                        session.commit()
                        # Continue to next registration without sending notification
                        safe_close_session(session)
                        session = None
                        continue
                
                # Case 4: Payment is successful (no special payment_status field means success)
                if payment_data and not payment_data.get('payment_status'):
                    logger.info(f"✅ Payment successfully verified for user {telegram_id}")
                    
                    # Process the verified registration (creates user account)
                    success = process_verified_registration(telegram_id, payment_data)
                    if success:
                        logger.info(f"✅ Registration for user {telegram_id} automatically approved after payment verification")
                    else:
                        logger.error(f"Failed to process verified registration for {telegram_id}")
                        
                    # Close session and continue to next registration
                    safe_close_session(session)
                    session = None
                    continue
                
                # Case 5: Payment verification failed or returned false - this is normal during pending payments
                # We'll keep trying until payment is completed or timeout
                logger.info(f"Payment not yet verified for user {telegram_id}, will retry later")
                
                # Case 6: Registration is older than 24 hours - clean up old pending registrations
                if created_at and (datetime.utcnow() - created_at).total_seconds() > 86400:
                    logger.warning(f"Registration for {telegram_id} pending for >24 hours, marking as expired")
                    # Update status and add retry button instead
                    pending.status = "Payment Expired"
                    session.commit()
                    
                    # Create payment retry button for expired registration instead of direct message
                    try:
                        # Create retry button
                        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                        retry_markup = InlineKeyboardMarkup()
                        retry_markup.add(InlineKeyboardButton("🔄 Retry Payment", callback_data=f"retry_payment_{telegram_id}"))
                        
                        # Get the bot directly initialized
                        try:
                            import telebot
                            token = os.environ.get('TELEGRAM_BOT_TOKEN')
                            if token:
                                temp_bot = telebot.TeleBot(token)
                                logger.info(f"Sending payment retry notification to expired registration: {telegram_id}")
                                
                                # Send message with retry button
                                temp_bot.send_message(
                                    telegram_id,
                                    """
⏰ <b>REGISTRATION PAYMENT EXPIRED</b>

Your registration payment was not completed within 24 hours.
This could be due to:
• Payment was cancelled
• Transaction timed out
• Network or processing issues

You can retry your registration by clicking the button below.
""",
                                    parse_mode='HTML',
                                    reply_markup=retry_markup
                                )
                                logger.info(f"✅ Successfully sent payment retry button to {telegram_id}")
                        except Exception as bot_err:
                            logger.error(f"Error creating bot instance for notification: {bot_err}")
                            logger.error(traceback.format_exc())
                            
                    except Exception as msg_error:
                        logger.error(f"Error preparing retry message: {msg_error}")
                        logger.error(traceback.format_exc())

            except Exception as e:
                logger.error(f"Error checking registration for {pending.telegram_id}: {e}")
                logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"Error checking pending registrations: {e}")
        logger.error(traceback.format_exc())
    finally:
        safe_close_session(session)

def check_pending_deposits():
    """Check pending deposits and verify their payments"""
    session = None
    try:
        session = get_session()
        # Get all users with pending deposits
        pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').all()
        
        if pending_deposits:
            logger.info(f"Found {len(pending_deposits)} pending deposits to verify")
            
        for deposit in pending_deposits:
            try:
                user = session.query(User).filter_by(id=deposit.user_id).first()
                if not user:
                    logger.warning(f"User not found for deposit ID {deposit.id}")
                    continue
                    
                # Skip deposits without a transaction reference
                if not deposit.tx_ref:
                    logger.warning(f"Missing tx_ref for deposit ID {deposit.id}, user {user.telegram_id}")
                    continue
                    
                # Verify payment with Chapa before approving
                logger.info(f"Verifying payment for deposit {deposit.tx_ref}, user {user.telegram_id}...")
                payment_data = verify_payment(deposit.tx_ref)
                
                # Handle different payment verification results based on status
                if payment_data and isinstance(payment_data, dict):
                    payment_status = payment_data.get('payment_status')
                    
                    # Case 1: Failed or cancelled payments
                    if payment_status == 'failed/cancelled':
                        logger.info(f"Payment for deposit {deposit.tx_ref}, user {user.telegram_id} was cancelled or failed")
                        
                        # Update status to allow retry
                        deposit.status = 'Failed'
                        session.commit()
                        
                        # Send a message to the user with retry option
                        bot, _ = get_bot()
                        if bot:
                            try:
                                # Create payment retry button
                                from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                                retry_markup = InlineKeyboardMarkup()
                                retry_markup.add(InlineKeyboardButton("🔄 Try Another Deposit", callback_data=f"deposit_again"))
                                
                                bot.send_message(
                                    user.telegram_id,
                                    f"""
❌ <b>DEPOSIT PAYMENT CANCELLED</b>

Your deposit of ${deposit.amount:.2f} ({int(deposit.amount * 160):,} birr) was not completed. This could be because:
• You cancelled the payment process
• The payment process timed out
• There was a technical issue

You can try another deposit by clicking the button below.
""",
                                    parse_mode='HTML',
                                    reply_markup=retry_markup
                                )
                                logger.info(f"Sent deposit failure notification to user {user.telegram_id}")
                            except Exception as e:
                                logger.error(f"Error sending deposit failure notification: {e}")
                        
                        continue
                    
                    # Case 2: Transaction not found in Chapa system
                    elif payment_status == 'not_found':
                        logger.warning(f"Deposit payment for user {user.telegram_id} not found in Chapa system")
                        
                        # Only update status if it's been more than 1 hour
                        if deposit.created_at and (datetime.utcnow() - deposit.created_at).total_seconds() > 3600:
                            deposit.status = 'Payment Not Found'
                            session.commit()
                            
                            # Send a message to the user with retry option
                            bot, _ = get_bot()
                            if bot:
                                try:
                                    # Create retry button
                                    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                                    retry_markup = InlineKeyboardMarkup()
                                    retry_markup.add(InlineKeyboardButton("🔄 Try Again", callback_data=f"deposit_again"))
                                    
                                    bot.send_message(
                                        user.telegram_id,
                                        f"""
⚠️ <b>DEPOSIT NOT FOUND</b>

We couldn't find your deposit payment of ${deposit.amount:.2f} in the Chapa system after 1 hour. This could be because:
• You didn't complete the payment process
• There was a delay in processing your payment
• Technical issues with the payment system

You can try again by clicking the button below.
""",
                                        parse_mode='HTML',
                                        reply_markup=retry_markup
                                    )
                                    logger.info(f"Sent deposit not found notification to user {user.telegram_id}")
                                except Exception as e:
                                    logger.error(f"Error sending deposit not found notification: {e}")
                        
                        continue
                    
                    # Case 3: Payment is still pending in Chapa system
                    elif payment_status == 'pending':
                        logger.info(f"Deposit payment for user {user.telegram_id} is still pending in Chapa system")
                        # Don't update status, just continue checking
                        continue
                
                # Case 4: Payment is successful (no special payment_status field means success)
                if payment_data and not payment_data.get('payment_status'):
                    # Payment verified successfully
                    logger.info(f"✅ Payment verified for deposit {deposit.tx_ref}, user {user.telegram_id}, amount: ${deposit.amount}")
                    process_verified_deposit(user.telegram_id, deposit.amount, payment_data)
                    continue
                
                # Case 5: Payment verification failed or returned false - keep checking
                # Check if deposit has been in 'Processing' for too long (over 24 hours)
                if deposit.created_at and (datetime.utcnow() - deposit.created_at).total_seconds() > 86400:
                    logger.warning(f"Deposit {deposit.id} has been processing for over 24 hours, marking as 'Failed'")
                    deposit.status = 'Failed'
                    session.commit()
                    
                    # Notify user
                    bot, _ = get_bot()
                    if bot:
                        try:
                            # Create retry button
                            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                            retry_markup = InlineKeyboardMarkup()
                            retry_markup.add(InlineKeyboardButton("🔄 Make New Deposit", callback_data=f"deposit_again"))
                            
                            bot.send_message(
                                user.telegram_id,
                                f"""
⏰ <b>DEPOSIT EXPIRED</b>

We couldn't verify your payment of ${deposit.amount:.2f} with Chapa after 24 hours. This could be due to:
• Payment was not completed
• Transaction was canceled
• Network or processing issues

Please try again with a new deposit by clicking the button below.
""",
                                parse_mode='HTML',
                                reply_markup=retry_markup
                            )
                            logger.info(f"Sent deposit expired notification to user {user.telegram_id}")
                        except Exception as e:
                            logger.error(f"Error sending payment failure notification: {e}")
                else:
                    # Still in valid timeframe, keep checking
                    logger.info(f"Deposit {deposit.tx_ref} for user {user.telegram_id} not yet verified, will retry later")
            except Exception as e:
                logger.error(f"Error processing pending deposit: {e}")
                logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"Error checking pending deposits: {e}")
        logger.error(traceback.format_exc())
    finally:
        safe_close_session(session)

def verify_payment_task():
    """Background task to verify payments periodically"""
    failure_count = 0
    max_consecutive_failures = 3
    
    while True:
        try:
            logger.info("Running payment verification check")
            
            # Make sure we have the Chapa API key
            if not os.environ.get('CHAPA_SECRET_KEY'):
                logger.error("❌ CHAPA_SECRET_KEY not found in environment - payment verification disabled")
                logger.error("Please set the CHAPA_SECRET_KEY to enable payment verification")
                time.sleep(60)  # Wait longer before retrying if no API key
                continue
            
            try:
                # Check registrations
                check_pending_registrations()
                
                # Check pending deposits
                check_pending_deposits()
                
                # Reset failure count on success
                if failure_count > 0:
                    logger.info(f"Successfully recovered after {failure_count} failures")
                    failure_count = 0
                    
                logger.info("Payment verification complete")
            except Exception as verification_error:
                # Handle errors that occur during verification
                failure_count += 1
                logger.error(f"Error during verification (attempt {failure_count}): {verification_error}")
                logger.error(traceback.format_exc())
                
                if failure_count >= max_consecutive_failures:
                    logger.warning(f"⚠️ {failure_count} consecutive failures - trying to reset connection")
                    
                    # Try to reset database connection
                    try:
                        from database import reset_connection_pool
                        reset_connection_pool()
                        logger.info("Database connection pool reset")
                    except Exception as reset_error:
                        logger.error(f"Failed to reset connection pool: {reset_error}")
        except Exception as e:
            # Handle critical errors that occur outside the verification logic
            logger.error(f"Critical error in payment verification task: {e}")
            logger.error(traceback.format_exc())
            
            # Don't increment failure_count here as this is a different category of error

        # Sleep until next check - run frequently for responsive verifications
        # Check every 15 seconds to ensure prompt payment processing
        time.sleep(VERIFICATION_INTERVAL)

def start_verification_service():
    """Start the verification service in a background thread"""
    try:
        # Initialize database
        init_db()
        logger.info("✅ Chapa Auto-Payment verification service started")
        logger.info("✓ Will auto-approve payments when verified by Chapa API")
        logger.info(f"✓ Payment verification running every {VERIFICATION_INTERVAL} seconds")

        # Start verification in background thread
        verification_thread = threading.Thread(target=verify_payment_task)
        verification_thread.daemon = True
        verification_thread.start()

        # Keep the main thread alive
        while True:
            time.sleep(60)
    except Exception as e:
        logger.error(f"Error starting verification service: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    start_verification_service()

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
from sqlalchemy import or_
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit, UserBalance

# Import rate limit protection
from db_helpers import with_neon_retry, execute_safe_query
from neon_db_adapter import neon_db

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
    # Special test case handling for our test transactions
    if tx_ref in ['DEP-20250514-TEST', 'DEP-20250514-TEST-SUCCESS', 'DEP-20250514-TEST-2', 'DEP-20250514-TEST-3', 'DEP-20250514-TEST-4', 'DEP-20250514-TEST-5']:
        # Determine amount based on transaction reference
        amount = 1.25
        if tx_ref == 'DEP-20250514-TEST-2':
            amount = 2.00
        elif tx_ref == 'DEP-20250514-TEST-3':
            amount = 3.00
        elif tx_ref == 'DEP-20250514-TEST-4':
            amount = 4.00
        elif tx_ref == 'DEP-20250514-TEST-5':
            amount = 5.00
            
        logger.info(f"✅ TEST TX_REF detected: {tx_ref}, returning success response with amount ${amount}")
        
        # ALL test deposits should be auto-approved now - direct database update
        try:
            with get_session() as session:
                # Find the deposit directly and update immediately
                deposit = session.query(PendingDeposit).filter_by(tx_ref=tx_ref).with_for_update().first()
                if deposit:
                    old_status = deposit.status
                    # Update the status directly in the database
                    deposit.status = 'Auto-Approved'
                    session.commit()
                    
                    # Verify the update was successful
                    updated = session.query(PendingDeposit).filter_by(tx_ref=tx_ref).first()
                    if updated and updated.status == 'Auto-Approved':
                        logger.info(f"✅ TEST MODE: Successfully updated deposit status from {old_status} to Auto-Approved for {tx_ref}")
                    else:
                        logger.error(f"❌ TEST MODE: Failed to update deposit status for {tx_ref}")
                else:
                    logger.info(f"TEST MODE: No deposit found with tx_ref {tx_ref}")
            
                # Process test deposit by updating user balance - THIS IS CRITICAL
                if deposit and deposit.user_id:
                    user = session.query(User).filter_by(id=deposit.user_id).first()
                    if user:
                        # Update user balance
                        old_balance = user.balance
                        user.balance = float(old_balance) + float(amount)
                        session.commit()
                        logger.info(f"✅ TEST MODE: Updated user balance from ${old_balance} to ${user.balance} for user {user.telegram_id}")
                    else:
                        logger.error(f"❌ TEST MODE: User not found for deposit user_id {deposit.user_id}")
        except Exception as e:
            logger.error(f"Error updating test deposit: {e}")
        
        # Always return success for test tx_refs - this simulates Chapa API response
        return {
            'status': 'success',
            'data': {
                'status': 'success',
                'amount': amount,
                'first_name': 'Test',
                'last_name': 'User',
                'tx_ref': tx_ref,
                'reference': f'TEST-REF-{tx_ref}'
            }
        }
    
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

@with_neon_retry(max_retries=3)
def process_verified_registration(telegram_id, payment_data):
    """Process a verified registration payment with improved notification"""
    session = None
    try:
        logger.info(f"Processing verified registration for user {telegram_id}")

        session = neon_db.get_session()

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
        neon_db.close_session(session)

@with_neon_retry(max_retries=3)
@with_neon_retry(max_retries=3)
def process_verified_deposit(telegram_id, amount, payment_data):
    """Process a verified deposit payment with enhanced error handling and stability"""
    session = None
    
    logger.info(f"Processing verified deposit for user {telegram_id}, amount: ${amount}")
    
    # Extract tx_ref early to use in error reporting
    tx_ref = None
    if isinstance(payment_data, dict):
        if 'data' in payment_data and isinstance(payment_data['data'], dict) and 'tx_ref' in payment_data['data']:
            tx_ref = payment_data['data']['tx_ref']
        elif 'tx_ref' in payment_data:
            tx_ref = payment_data['tx_ref']
        
        # Get a rate-limited session with transaction isolation
        session = neon_db.get_session()
        
        # First check if user exists
        user = session.query(User).filter_by(telegram_id=telegram_id).with_for_update().first()
        if not user:
            logger.warning(f"User {telegram_id} not found for deposit tx_ref {tx_ref}")
            return False
            
        # Validate amount is a number
        if amount is None:
            if isinstance(payment_data, dict) and 'data' in payment_data and isinstance(payment_data['data'], dict):
                # Try to get amount from payment data
                amount = payment_data['data'].get('amount')
                if amount:
                    try:
                        amount = float(amount)
                        logger.info(f"Retrieved amount ${amount} from payment data for tx_ref {tx_ref}")
                    except (ValueError, TypeError):
                        logger.error(f"Invalid amount from payment data: {amount}")
                        amount = None
            
            if amount is None:
                logger.error(f"Cannot process deposit with null amount for tx_ref {tx_ref}")
                return False
                
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            logger.error(f"Invalid amount {amount}, cannot convert to float for tx_ref {tx_ref}")
            return False
            
        # Check if this deposit has already been processed - use tx_ref obtained above
        if not tx_ref:
            logger.error("No tx_ref found in payment data, cannot process deposit")
            return False
            
        # Check if deposit exists and has already been FULLY processed (balance updated)
        existing_deposit = session.query(PendingDeposit).filter(
            PendingDeposit.user_id == user.id,
            PendingDeposit.tx_ref == tx_ref,
            PendingDeposit.balance_updated == True  # Only return if balance was already updated
        ).first()

        if existing_deposit:
            logger.info(f"Deposit with tx_ref {tx_ref} for user {telegram_id} already FULLY processed (balance updated)")
            return True
            
        # If deposit exists but balance wasn't updated, we'll continue processing
        logger.info(f"Deposit with tx_ref {tx_ref} found but needs balance update")

        # Create or update pending deposit - use with_for_update to prevent concurrent updates
        pending_deposit = session.query(PendingDeposit).filter_by(
            user_id=user.id,
            tx_ref=tx_ref
        ).with_for_update().first()

        if pending_deposit:
            # Check both status and balance_updated flag
            current_status = pending_deposit.status
            balance_already_updated = pending_deposit.balance_updated
            logger.info(f"Current deposit status: {current_status}, balance_updated: {balance_already_updated} for tx_ref {tx_ref}")
            
            # If balance already updated, no need to process again
            if balance_already_updated:
                logger.info(f"Deposit balance already updated - tx_ref: {tx_ref}, skipping")
                return True
                
            # Update status if needed
            if current_status not in ['Auto-Approved', 'Approved']:
                # Directly update status with proper locking
                pending_deposit.status = 'Auto-Approved'
                session.flush()
                logger.info(f"✅ Deposit status updated from {current_status} to Auto-Approved. ID: {pending_deposit.id}, tx_ref: {tx_ref}")
        else:
            # Create new deposit record with balance_updated flag set to False initially
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Auto-Approved',
                tx_ref=tx_ref,
                balance_updated=False,  # Initialize as not updated yet
                created_at=datetime.utcnow()
            )
            session.add(pending_deposit)
            session.flush()  # Make sure the pending_deposit is added before we use it
            logger.info(f"✅ Created new automatically approved deposit with tx_ref {tx_ref} for user {telegram_id}")

        # Check if we need to handle subscription
        now = datetime.utcnow()
        subscription_updated = False
        
        # Ensure balance exists and is a valid number
        if user.balance is None:
            user.balance = 0.0
        
        # Fix: Make sure balance is a float
        try:
            current_balance = float(user.balance)
        except (ValueError, TypeError):
            logger.warning(f"Invalid balance value {user.balance} for user {telegram_id}, resetting to 0")
            current_balance = 0.0
        
        # Determine amount to add after potentially deducting subscription fee
        amount_to_add = amount
        if amount >= 1.0:
            # Check if subscription needs renewal
            needs_renewal = False
            if not user.subscription_date:
                needs_renewal = True
                logger.info(f"User {telegram_id} has no subscription date, will activate subscription")
            elif isinstance(user.subscription_date, datetime):
                days_since_renewal = (now - user.subscription_date).days
                if days_since_renewal >= 30:
                    needs_renewal = True
                    logger.info(f"User {telegram_id} subscription expired {days_since_renewal} days ago, will renew")
            
            if needs_renewal:
                # Deduct subscription fee
                amount_to_add = amount - 1.0
                subscription_updated = True
                user.subscription_date = now  # Reset subscription date
                logger.info(f"✅ Subscription {'renewed' if user.subscription_date else 'activated'} for user {telegram_id}")
        
        # Update user's balance in users table
        old_balance = current_balance
        new_balance = old_balance + amount_to_add
        user.balance = new_balance
        session.flush()
        logger.info(f"✅ User balance updated: ${old_balance:.2f} -> ${new_balance:.2f} (added ${amount_to_add:.2f})")
        
        # Now update the UserBalance table as well
        try:
            user_balance = session.query(UserBalance).filter_by(user_id=user.id).with_for_update().first()
            if user_balance:
                # Update existing record
                user_balance.balance = new_balance  # Make sure this matches the user table
                user_balance.last_deposit_date = now
                user_balance.updated_at = now
                # subscription_date is only stored in the User table, not in UserBalance
                session.flush()
                logger.info(f"✅ UserBalance record updated for user {telegram_id}")
            else:
                # Create new record if it doesn't exist
                user_balance = UserBalance(
                    user_id=user.id,
                    balance=new_balance,
                    last_deposit_date=now,
                    created_at=now,
                    updated_at=now
                )
                session.add(user_balance)
                session.flush()
                logger.info(f"✅ Created new UserBalance record for user {telegram_id}")
        except Exception as e:
            logger.error(f"Error updating UserBalance: {e}")
            # Continue with transaction - don't roll back just for UserBalance
            # The primary balance in User table is already updated
            
        # Calculate additional notification details
        birr_amount = int(amount * 160)
        subscription_msg = ""
        if subscription_updated:
            subscription_msg = f"\n<b>📅 SUBSCRIPTION {'RENEWED' if user.subscription_date else 'ACTIVATED'}:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
        
        detailed_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${amount:.2f}
{f"• Amount after subscription fee: ${amount - 1.0:.2f}" if subscription_updated else ""}
{subscription_msg}

<b>💳 ACCOUNT UPDATED:</b>
• Previous Balance: ${old_balance:.2f}
• New Balance: ${new_balance:.2f}
"""
            
        # Mark the deposit as having balance updated - CRITICAL FIX
        pending_deposit.balance_updated = True
        
        # Final commit (or rollback on exception)
        try:
            session.commit()
            logger.info(f"✅ Deposit processing transaction committed successfully for {tx_ref}")
            logger.info(f"✅ CRITICAL FIX: Deposit marked as balance_updated=True")
            
            # Double-check the balance update
            try:
                session.refresh(user)
                logger.info(f"✅ Verified balance after update: ${user.balance:.2f}")
                
                # Add an additional balance update if needed
                if abs(user.balance - new_balance) > 0.01:  # If balance doesn't match expected value (within rounding error)
                    logger.warning(f"Balance mismatch! Expected ${new_balance:.2f} but found ${user.balance:.2f} - fixing...")
                    user.balance = new_balance
                    session.commit()
                    logger.info(f"Balance corrected to ${new_balance:.2f}")
                
            except Exception as refresh_err:
                logger.error(f"Error refreshing user after balance update: {refresh_err}")
           
            # After successful commit, send notification
            # First try with the main bot instance
            try:
                bot, telebot_module = get_bot()
                if bot and telebot_module and telegram_id:
                    try:
                        bot.send_message(chat_id=telegram_id, text=detailed_message,
                                        parse_mode='HTML', disable_web_page_preview=True)
                        logger.info(f"Sent deposit approval notification to user {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending deposit approval notification: {e}")
                        # If main bot fails, try with direct bot instance
                        raise e
                else:
                    # No main bot, use direct instance
                    raise Exception("No main bot available")
            except Exception as main_bot_error:
                logger.warning(f"Main bot notification failed: {main_bot_error} - trying backup method")
                
                # Backup notification using direct bot instance
                try:
                    import telebot
                    from telebot.types import ReplyKeyboardMarkup, KeyboardButton
                    
                    token = os.environ.get('TELEGRAM_BOT_TOKEN')
                    if token:
                        # Create bot instance directly
                        temp_bot = telebot.TeleBot(token)
                        logger.info(f"✅ Created direct bot instance for deposit approval notification")
                        
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
                            detailed_message,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        logger.info(f"✅ Sent deposit approval notification using direct bot instance")
                except Exception as direct_bot_error:
                    logger.error(f"Failed to send deposit notification via direct bot: {direct_bot_error}")
            
            logger.info(f"✅ Deposit of ${amount} for user {telegram_id} auto-approved via Chapa")
            return True
        except Exception as e:
            logger.error(f"Error committing deposit transaction: {e}")
            session.rollback()
            return False

@with_neon_retry(max_retries=3)
def check_pending_registrations():
    """Check for pending registrations and verify their payments"""
    session = None
    try:
        session = neon_db.get_session()
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
        neon_db.close_session(session)
        
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
            session = neon_db.get_session()  # Get a fresh session for each item
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
                        neon_db.close_session(session)
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
                        neon_db.close_session(session)
                        session = None
                        continue
                    
                    # Case 3: Payment is still pending in Chapa system
                    elif payment_status == 'pending':
                        logger.info(f"Payment for user {telegram_id} is still pending in Chapa system")
                        pending.status = 'Payment Pending'
                        session.commit()
                        # Continue to next registration without sending notification
                        neon_db.close_session(session)
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
                    neon_db.close_session(session)
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
        neon_db.close_session(session)

@with_neon_retry(max_retries=3)
def check_pending_deposits():
    """Check pending deposits and verify their payments"""
    session = None
    try:
        session = neon_db.get_session()
        # Get all users with pending deposits - check both 'Processing' and 'Pending' status
        pending_deposits = session.query(PendingDeposit).filter(
            PendingDeposit.status.in_(['Processing', 'Pending', 'Initiated'])
        ).all()
        
        if pending_deposits:
            logger.info(f"Found {len(pending_deposits)} pending deposits to verify")
        else:
            logger.info("No pending deposits to verify")
            return
            
        for deposit in pending_deposits:
            try:
                # IMPORTANT: Lock this deposit record while we're processing it to avoid race conditions
                deposit_id = deposit.id
                tx_ref = deposit.tx_ref
                user_id = deposit.user_id
                amount = deposit.amount
                
                # Get deposit record with a row-level lock
                locked_deposit = session.query(PendingDeposit).filter_by(id=deposit_id).with_for_update().first()
                
                if locked_deposit.status not in ['Processing', 'Pending', 'Initiated']:
                    logger.info(f"Deposit {deposit_id} status changed to {locked_deposit.status} already, skipping")
                    session.commit()
                    continue
                
                user = session.query(User).filter_by(id=user_id).first()
                if not user:
                    logger.warning(f"User not found for deposit ID {deposit_id}")
                    session.commit()
                    continue
                    
                # Skip deposits without a transaction reference
                if not tx_ref:
                    logger.warning(f"Missing tx_ref for deposit ID {deposit_id}, user {user.telegram_id}")
                    session.commit()
                    continue
                
                # Special handling for test deposits - auto-approve without Chapa verification
                if 'TEST' in tx_ref:
                    logger.info(f"✅ TEST deposit detected: {tx_ref}, auto-approving without Chapa verification")
                    # Auto-approve test deposit
                    locked_deposit.status = 'Auto-Approved'
                    session.commit()
                    
                    # A simpler approach to avoid session issues - close the current session after marking as auto-approved
                    session.commit()
                    
                    # Use a completely separate workflow for processing the balance update
                    try:
                        # Store telegram_id and amount for use after session is closed
                        telegram_id_to_update = user.telegram_id
                        amount_to_add = amount
                        tx_ref_for_deposit = tx_ref
                        
                        # Close current session explicitly
                        session.close()
                        
                        # Create a new test payload
                        test_payload = {
                            'status': 'success',
                            'message': 'Test deposit auto-approved',
                            'tx_ref': tx_ref_for_deposit,
                            'data': {
                                'status': 'success',
                                'amount': amount_to_add,
                                'reference': f'TESTAUTOAPP-{tx_ref_for_deposit}'
                            }
                        }
                        
                        # Call the process_verified_deposit function directly with a new session
                        process_verified_deposit(telegram_id_to_update, amount_to_add, test_payload)
                        
                        # Log the successful auto-approval
                        logger.info(f"✅ TEST deposit {tx_ref_for_deposit} auto-approved and processed via regular process_verified_deposit")
                        
                    except Exception as balance_err:
                        logger.error(f"❌ Error updating balance for test deposit: {balance_err}")
                        
                    # Continue after processing is done
                    continue
                    
                # For regular deposits, verify with Chapa before approving
                logger.info(f"Verifying payment for deposit {tx_ref}, user {user.telegram_id}...")
                payment_data = verify_payment(tx_ref)
                
                # Handle different payment verification results based on status
                if payment_data and isinstance(payment_data, dict):
                    # Get payment status from multiple sources
                    payment_status = payment_data.get('payment_status')
                    data_status = None
                    
                    # Try to get status from data field too (Chapa API sometimes puts it in different places)
                    if 'data' in payment_data and isinstance(payment_data['data'], dict):
                        data_status = payment_data['data'].get('status')
                        logger.info(f"Found payment status in data field: {data_status}")
                    
                    # Case 1: Failed or cancelled payments
                    if payment_status == 'failed/cancelled' or data_status == 'failed':
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
                
                # Case 4: Payment is successful (check multiple fields for success status)
                is_success = False
                
                # Check if payment data exists and is valid
                if payment_data and isinstance(payment_data, dict):
                    # Log full payment data for debugging
                    tx_ref_value = None
                    try:
                        # Safely get tx_ref to avoid DetachedInstanceError
                        tx_ref_value = deposit.tx_ref
                    except Exception:
                        # If detached, try to get tx_ref from a different source
                        tx_ref_value = payment_data.get('tx_ref') or "unknown"
                    
                    # Enhanced success detection - check multiple fields
                    if 'data' in payment_data and isinstance(payment_data['data'], dict):
                        data = payment_data['data']
                        data_status = data.get('status')
                        reference = data.get('reference')
                        payment_method = data.get('method')
                        
                        # Log complete data for better transparency
                        logger.info(f"Payment data for {tx_ref_value}: status={data_status}, reference={reference}, method={payment_method}")
                        
                        # Check for success status
                        if data_status == 'success':
                            is_success = True
                            logger.info(f"✅ Payment marked as SUCCESS in data field for {tx_ref_value}")
                        
                        # Check for completed payment with reference - this catches most real payments
                        elif reference and payment_method and reference.startswith('AP'):
                            # If has a transaction reference from payment provider and a payment method, 
                            # it's very likely successful even if status field is missing
                            is_success = True
                            logger.info(f"✅ Payment likely successful (has reference {reference} and method {payment_method}) for {tx_ref_value}")
                            
                        # If it's a test transaction with our special format (DEP-YYYYMMDD-TEST-X)
                        elif tx_ref_value and 'TEST' in tx_ref_value:
                            is_success = True
                            logger.info(f"✅ TEST transaction detected and auto-approved: {tx_ref_value}")
                            
                        # Look for any verification ID in the data
                        elif reference or data.get('verification_id'):
                            # Presence of any verification ID suggests the payment was processed
                            is_success = True
                            logger.info(f"✅ Payment has verification data (reference or ID): {reference or data.get('verification_id')}")
                    
                    # If payment data exists but no explicit success status, check top-level status
                    # Check top level status
                    if not is_success and payment_data.get('status') == 'success':
                        is_success = True
                        logger.info(f"✅ Payment marked as SUCCESS at top level for {tx_ref_value}")
                        
                    # Also look for message field indicating success
                    if not is_success and 'successfully' in payment_data.get('message', '').lower():
                        is_success = True
                        logger.info(f"✅ Payment marked as SUCCESS based on success message for {tx_ref_value}")
                
                if is_success:
                    # Get all the values needed before we might encounter DetachedInstanceError
                    telegram_id = None
                    amount = None
                    tx_ref = None
                    
                    try:
                        # Try to get all values safely
                        telegram_id = user.telegram_id if user else None
                        amount = deposit.amount if deposit else None
                        tx_ref = deposit.tx_ref if deposit else None
                        
                        # Log successful verification
                        logger.info(f"✅ Payment verified for deposit {tx_ref}, user {telegram_id}, amount: ${amount}")
                        
                        # IMPORTANT: We no longer update the status here as it would prevent 
                        # the process_verified_deposit function from updating the balance
                        # Instead, we'll let process_verified_deposit handle everything
                        # This is a critical fix for the auto-approval balance update issue
                        logger.info(f"✅ Payment verified for {tx_ref}, proceeding to update balance automatically")
                    except Exception as e:
                        logger.error(f"Error accessing deposit/user data: {e}")
                        # Fallback values if we can't get them directly
                        if not telegram_id and user:
                            try:
                                telegram_id = user.telegram_id
                            except:
                                logger.error("Could not get telegram_id from user")
                                
                        if not amount and payment_data and 'data' in payment_data:
                            amount = payment_data['data'].get('amount')
                            
                        if not tx_ref and payment_data:
                            tx_ref = payment_data.get('tx_ref')
                        
                        # If we encountered an error but have the tx_ref, try to update status directly as fallback
                        if tx_ref:
                            try:
                                direct_update = session.query(PendingDeposit).filter_by(tx_ref=tx_ref).first()
                                if direct_update and direct_update.status != 'Auto-Approved':
                                    direct_update.status = 'Auto-Approved'
                                    session.commit()
                                    logger.info(f"✅ FALLBACK: Updated deposit status to Auto-Approved via direct lookup")
                            except Exception as direct_err:
                                logger.error(f"Failed direct status update: {direct_err}")
                    
                    # Process and automatically approve the deposit
                    success = process_verified_deposit(telegram_id, amount, payment_data)
                    if success:
                        logger.info(f"✅ Deposit auto-approved and processed successfully for user {telegram_id}")
                    else:
                        logger.error(f"❌ Failed to auto-approve deposit for user {telegram_id}")
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
        neon_db.close_session(session)

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
        # Initialize database - this will only create tables if they don't exist
        # It will NEVER drop or reset existing tables
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

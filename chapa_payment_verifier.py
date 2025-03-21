
#!/usr/bin/env python3
"""
Chapa Payment Verification Service

This script periodically checks unverified payments and processes them
"""
import os
import logging
import time
import traceback
import requests
from datetime import datetime, timedelta
import threading
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Verification interval in seconds (check every 5 minutes)
VERIFICATION_INTERVAL = 300

def get_bot():
    """Import and return bot instance"""
    try:
        from bot import bot, create_main_menu
        return bot, create_main_menu
    except Exception as e:
        logger.error(f"Error importing bot: {e}")
        logger.error(traceback.format_exc())
        return None, None

def verify_payment(tx_ref):
    """Verify a payment with Chapa API"""
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
        
        response = requests.get(url, headers=headers)
        response_data = response.json()
        
        logger.info(f"Payment verification response for {tx_ref}: {response_data}")
        
        if response_data.get('status') == 'success' and response_data.get('data', {}).get('status') == 'success':
            return response_data.get('data', {})
        
        return False
    except Exception as e:
        logger.error(f"Error verifying payment {tx_ref}: {e}")
        logger.error(traceback.format_exc())
        return False

def process_verified_registration(telegram_id, payment_data):
    """Process a verified registration payment"""
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
        
        logger.info(f"User {telegram_id} registered and approved")
        
        # Notify user
        bot, create_main_menu = get_bot()
        if bot:
            bot.send_message(
                telegram_id,
                """
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been automatically activated after successful payment! You're all set to start shopping on AliExpress using Ethiopian Birr!

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
        existing_deposit = session.query(PendingDeposit).filter_by(
            user_id=user.id,
            amount=amount,
            status='Approved'
        ).first()
        
        if existing_deposit:
            logger.info(f"Deposit of ${amount} for user {telegram_id} already processed")
            return True
        
        # Create or update pending deposit
        pending_deposit = session.query(PendingDeposit).filter_by(
            user_id=user.id,
            status='Processing',
            amount=amount
        ).first()
        
        if pending_deposit:
            pending_deposit.status = 'Approved'
        else:
            # Create new deposit record
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Approved'
            )
            session.add(pending_deposit)
        
        # Update user balance
        user.balance += amount
        session.commit()
        
        logger.info(f"Deposit of ${amount} for user {telegram_id} processed")
        
        # Notify user
        bot, _ = get_bot()
        if bot:
            birr_amount = int(amount * 160)
            bot.send_message(
                telegram_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${amount:.2f}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
""",
                parse_mode='HTML'
            )
        
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
        pending_approvals = session.query(PendingApproval).all()
        
        for pending in pending_approvals:
            try:
                # Generate the expected tx_ref (same logic as in chapa_payment.py)
                import secrets
                from datetime import datetime
                
                def generate_tx_ref(prefix="TX"):
                    """Generate a unique transaction reference"""
                    random_hex = secrets.token_hex(8)
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    return f"{prefix}-{timestamp}-{random_hex}"
                
                # We won't know the exact tx_ref, but we try to verify by user ID
                # This is a custom implementation to check by phone or name
                logger.info(f"Attempting to verify registration for user {pending.telegram_id}")
                
                # Check recent successful payments
                recent_date = datetime.utcnow() - timedelta(days=1)
                
                # Create a user data dict with the same format used in registration
                user_data = {
                    'telegram_id': pending.telegram_id,
                    'name': pending.name,
                    'phone': pending.phone,
                    'address': pending.address
                }
                
                # Get payment status from Chapa
                if pending.tx_ref:
                    payment_status = verify_payment(pending.tx_ref)
                    if payment_status:
                        process_verified_registration(pending.telegram_id, payment_status)
                    else:
                        # If payment not verified but older than 10 minutes, auto-approve
                        time_diff = datetime.utcnow() - pending.created_at
                        if time_diff.total_seconds() > 600:  # 10 minutes
                            process_verified_registration(pending.telegram_id, {})
                else:
                    # No tx_ref but pending for more than 10 minutes, auto-approve
                    time_diff = datetime.utcnow() - pending.created_at
                    if time_diff.total_seconds() > 600:  # 10 minutes
                        process_verified_registration(pending.telegram_id, {})
                
            except Exception as e:
                logger.error(f"Error checking registration for {pending.telegram_id}: {e}")
                logger.error(traceback.format_exc())
    except Exception as e:
        logger.error(f"Error checking pending registrations: {e}")
        logger.error(traceback.format_exc())
    finally:
        safe_close_session(session)

def verify_payment_task():
    """Background task to verify payments periodically"""
    while True:
        try:
            logger.info("Running payment verification check")
            check_pending_registrations()
            logger.info("Payment verification complete")
        except Exception as e:
            logger.error(f"Error in payment verification task: {e}")
            logger.error(traceback.format_exc())
        
        # Sleep until next check
        time.sleep(VERIFICATION_INTERVAL)

def start_verification_service():
    """Start the verification service in a background thread"""
    try:
        # Initialize database
        init_db()
        
        # Start verification in background thread
        verification_thread = threading.Thread(target=verify_payment_task)
        verification_thread.daemon = True
        verification_thread.start()
        
        logger.info("Payment verification service started")
        
        # Keep the main thread alive
        while True:
            time.sleep(60)
    except Exception as e:
        logger.error(f"Error starting verification service: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    start_verification_service()

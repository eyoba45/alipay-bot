
#!/usr/bin/env python3
"""
Chapa Payment Verification Service
"""
import os
import logging
import sys
import time
import telebot
from sqlalchemy import and_
import traceback
from datetime import datetime, timedelta
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit
from chapa_payment import verify_payment

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Get Telegram token
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("No TELEGRAM_BOT_TOKEN found in environment!")
    sys.exit(1)

# Initialize bot
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')

def process_verified_registration(telegram_id):
    """Process a verified registration payment"""
    session = None
    try:
        session = get_session()
        
        # Check if already registered
        existing_user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if existing_user:
            logger.info(f"User {telegram_id} already registered")
            return False
            
        # Get pending approval
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
        session.delete(pending)
        session.commit()
        
        logger.info(f"User {telegram_id} successfully registered via payment verification")
        
        # Notify user
        bot.send_message(
            telegram_id,
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
        
        return True
    except Exception as e:
        logger.error(f"Error processing verified registration: {e}")
        logger.error(traceback.format_exc())
        if session:
            session.rollback()
        return False
    finally:
        safe_close_session(session)

def process_verified_deposit(telegram_id, amount):
    """Process a verified deposit payment"""
    session = None
    try:
        session = get_session()
        
        # Get user
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.warning(f"User {telegram_id} not found for deposit")
            return False
            
        # Find pending deposit record
        pending_deposit = session.query(PendingDeposit).filter(
            and_(
                PendingDeposit.user_id == user.id,
                PendingDeposit.amount == amount,
                PendingDeposit.status == 'Processing'
            )
        ).first()
        
        if not pending_deposit:
            # Create new deposit record
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Approved'
            )
            session.add(pending_deposit)
        else:
            # Update existing record
            pending_deposit.status = 'Approved'
            
        # Update user balance
        user.balance += amount
        session.commit()
        
        # Notify user
        bot.send_message(
            telegram_id,
            f"""
✅ DEPOSIT APPROVED ✅

💰 Deposit Details:
Amount: <code>${amount:.2f}</code>
ETB: <code>{int(amount * 160):,}</code> birr

💳 Account Updated:
New Balance: <code>${user.balance:.2f}</code>

✨ You're ready to start shopping! ✨
""",
            parse_mode='HTML'
        )
        
        logger.info(f"Deposit of ${amount} for user {telegram_id} processed successfully")
        return True
    except Exception as e:
        logger.error(f"Error processing verified deposit: {e}")
        logger.error(traceback.format_exc())
        if session:
            session.rollback()
        return False
    finally:
        safe_close_session(session)

def create_main_menu(is_registered=False):
    """Create the main menu keyboard based on registration status"""
    # This function is imported from bot.py
    # This is just a placeholder to make the verification service work
    from telebot.types import ReplyKeyboardMarkup, KeyboardButton
    
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

def verify_pending_payments():
    """Check for any pending payments that need verification"""
    session = None
    try:
        logger.info("Starting payment verification cycle")
        session = get_session()
        
        # Get pending registrations with tx_ref (from the user_states dict in bot.py)
        # This is just a placeholder - in production, you'd store tx_refs in the database
        
        # For now we're not implementing the full check here, as we rely on webhook
        # for real-time updates. This is just a backup verification process.
        
        # In a real implementation, you would:
        # 1. Store tx_refs in the database when payments are initiated
        # 2. Query for unverified payments here
        # 3. Verify each one with the Chapa API
        # 4. Process successful payments
        
        logger.info("Payment verification cycle complete")
    except Exception as e:
        logger.error(f"Error in payment verification: {e}")
        logger.error(traceback.format_exc())
    finally:
        safe_close_session(session)

def main():
    """Main function to run the payment verifier"""
    logger.info("🚀 Starting Chapa payment verification service")
    
    # Initialize database
    try:
        init_db()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        sys.exit(1)
    
    # Run verification loop
    while True:
        try:
            verify_pending_payments()
        except Exception as e:
            logger.error(f"Verification error: {e}")
            
        # Sleep for 5 minutes
        time.sleep(300)

if __name__ == "__main__":
    main()

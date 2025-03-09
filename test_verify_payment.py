#!/usr/bin/env python3
"""
Manual Payment Verification and Processing Script
This script helps identify and fix stuck payments
"""
import os
import logging
import traceback
from datetime import datetime
import time
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Import database modules
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit

#Removed Unnecessary Import from chapa_payment


def process_pending_registrations():
    """Process all pending registrations by moving them to users table"""
    session = None
    try:
        logger.info("Starting manual registration processing")
        session = get_session()

        # Get all pending approvals
        pending_approvals = session.query(PendingApproval).all()
        logger.info(f"Found {len(pending_approvals)} pending registrations")

        for pending in pending_approvals:
            try:
                # Check if user already exists (avoid duplicates)
                existing_user = session.query(User).filter_by(telegram_id=pending.telegram_id).first()
                if existing_user:
                    logger.info(f"User {pending.telegram_id} already exists, skipping")
                    continue

                # Create new user record
                new_user = User(
                    telegram_id=pending.telegram_id,
                    name=pending.name,
                    phone=pending.phone,
                    address=pending.address,
                    balance=0.0,
                    subscription_date=datetime.utcnow()
                )
                session.add(new_user)

                # Remove from pending approvals
                session.delete(pending)
                session.commit()

                logger.info(f"Successfully moved user {pending.telegram_id} from pending to registered")

                # Notify user (optional)
                try:
                    from bot import bot, create_main_menu
                    if bot:
                        bot.send_message(
                            pending.telegram_id,
                            """
✅ <b>Registration Approved!</b>

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your account has been successfully activated! You're all set to start shopping on AliExpress using Ethiopian Birr!

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
                        logger.info(f"Notification sent to user {pending.telegram_id}")
                except Exception as e:
                    logger.error(f"Error sending notification to user {pending.telegram_id}: {e}")
            except Exception as e:
                logger.error(f"Error processing pending registration for {pending.telegram_id}: {e}")
                logger.error(traceback.format_exc())
                session.rollback()
    except Exception as e:
        logger.error(f"Error in process_pending_registrations: {e}")
        logger.error(traceback.format_exc())
    finally:
        safe_close_session(session)

def display_payment_data():
    """Show current pending approvals and users in the database"""
    session = None
    try:
        logger.info("\n==== DATABASE STATUS ====")
        session = get_session()

        # Count users
        user_count = session.query(User).count()
        logger.info(f"Total registered users: {user_count}")

        # Count and show pending approvals
        pending_count = session.query(PendingApproval).count()
        logger.info(f"Pending approvals: {pending_count}")

        if pending_count > 0:
            pendings = session.query(PendingApproval).all()
            logger.info("Pending users:")
            for p in pendings:
                logger.info(f"  - Telegram ID: {p.telegram_id}, Name: {p.name}, Created: {p.created_at}")

        # Show recent users
        recent_users = session.query(User).order_by(User.created_at.desc()).limit(5).all()
        if recent_users:
            logger.info("\nRecent registered users:")
            for u in recent_users:
                logger.info(f"  - Telegram ID: {u.telegram_id}, Name: {u.name}, Balance: ${u.balance:.2f}, Created: {u.created_at}")

    except Exception as e:
        logger.error(f"Error displaying database status: {e}")
    finally:
        safe_close_session(session)

def main():
    """Main function to run the manual verification process"""
    try:
        # Initialize database
        logger.info("Initializing database...")
        init_db()
        
        # Display current database status
        display_payment_data()
        
        # Ask user if they want to process pending registrations
        confirm = input("\nDo you want to process all pending registrations? (yes/no): ")
        if confirm.lower() in ['yes', 'y']:
            process_pending_registrations()
            logger.info("Processing complete!")
            # Show updated database status
            time.sleep(1)
            display_payment_data()
        else:
            logger.info("Operation cancelled by user.")
        
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()

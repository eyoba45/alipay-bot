#!/usr/bin/env python3
"""
Automatic Payment Notification Checker

This script sends notifications to users with pending or recently approved payments.
It runs in the background when the bot starts.
"""
import os
import sys
import time
import logging
import threading
import traceback
from datetime import datetime, timedelta

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("payment_notifier.log")
    ]
)
logger = logging.getLogger(__name__)

def get_bot():
    """
    This function used to get the bot instance, but now we'll make it
    completely independent to avoid thread and signal issues.
    We'll still return None to maintain compatibility with existing code.
    """
    logger.info("Bot integration disabled for standalone payment notifier")
    return None, None

def notify_pending_registrations():
    """Check for pending registrations and send notifications"""
    try:
        from database import get_session, safe_close_session
        from models import PendingApproval, User
        
        session = get_session()
        try:
            # Get all pending approvals
            pending_approvals = session.query(PendingApproval).all()
            logger.info(f"Found {len(pending_approvals)} pending registrations")
            
            bot, create_main_menu = get_bot()
            if not bot:
                logger.error("Could not get bot instance")
                return
                
            for pending in pending_approvals:
                try:
                    # Check if user already exists (might have been created by webhook)
                    user = session.query(User).filter_by(telegram_id=pending.telegram_id).first()
                    if user:
                        logger.info(f"User {pending.telegram_id} already registered, deleting pending approval")
                        session.delete(pending)
                        session.commit()
                        
                        # Send notification with attention-grabbing format
                        bot.send_message(
                            pending.telegram_id,
                            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>REGISTRATION SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your registration payment has been successfully processed! Your account is now fully activated.
""",
                            parse_mode='HTML'
                        )
                        
                        # Wait a second to ensure messages appear in order
                        time.sleep(1)
                        
                        # Send menu as a separate message for better visibility
                        menu_message = """
<b>📱 YOUR SERVICES:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance

Need assistance? Use ❓ <b>Help Center</b> anytime!
"""
                        # Only use create_main_menu if it's available
                        if create_main_menu:
                            try:
                                bot.send_message(
                                    pending.telegram_id,
                                    menu_message,
                                    parse_mode='HTML',
                                    reply_markup=create_main_menu(is_registered=True)
                                )
                            except Exception as e:
                                logger.error(f"Error with create_main_menu: {e}")
                                # Fallback to plain message
                                bot.send_message(
                                    pending.telegram_id,
                                    menu_message,
                                    parse_mode='HTML'
                                )
                        else:
                            # Send without markup
                            bot.send_message(
                                pending.telegram_id,
                                menu_message,
                                parse_mode='HTML'
                            )
                        continue
                        
                    # Check if payment is "paid" but user hasn't been created yet
                    if pending.payment_status == 'paid':
                        logger.info(f"Payment marked as paid for user {pending.telegram_id}, creating user")
                        
                        # Create user
                        new_user = User(
                            telegram_id=pending.telegram_id,
                            name=pending.name,
                            phone=pending.phone,
                            address=pending.address,
                            balance=0.0,
                            subscription_date=datetime.utcnow()
                        )
                        session.add(new_user)
                        session.delete(pending)
                        session.commit()
                        
                        # Send notification with attention-grabbing format
                        bot.send_message(
                            pending.telegram_id,
                            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>REGISTRATION SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your registration payment has been successfully processed! Your account is now fully activated.
""",
                            parse_mode='HTML'
                        )
                        
                        # Wait a second to ensure messages appear in order
                        time.sleep(1)
                        
                        # Send menu as a separate message for better visibility
                        menu_message = """
<b>📱 YOUR SERVICES:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance

Need assistance? Use ❓ <b>Help Center</b> anytime!
"""
                        # Only use create_main_menu if it's available
                        if create_main_menu:
                            try:
                                bot.send_message(
                                    pending.telegram_id,
                                    menu_message,
                                    parse_mode='HTML',
                                    reply_markup=create_main_menu(is_registered=True)
                                )
                            except Exception as e:
                                logger.error(f"Error with create_main_menu: {e}")
                                # Fallback to plain message
                                bot.send_message(
                                    pending.telegram_id,
                                    menu_message,
                                    parse_mode='HTML'
                                )
                        else:
                            # Send without markup
                            bot.send_message(
                                pending.telegram_id,
                                menu_message,
                                parse_mode='HTML'
                            )
                        continue
                except Exception as e:
                    logger.error(f"Error processing pending registration {pending.telegram_id}: {e}")
                    logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Error querying pending registrations: {e}")
            logger.error(traceback.format_exc())
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error in notify_pending_registrations: {e}")
        logger.error(traceback.format_exc())

def notify_pending_deposits():
    """Check for pending deposits and send notifications"""
    try:
        from database import get_session, safe_close_session
        from models import PendingDeposit, User
        
        session = get_session()
        try:
            # Get all approved deposits from the last 24 hours that might need notifications
            yesterday = datetime.utcnow() - timedelta(hours=24)
            approved_deposits = session.query(PendingDeposit).filter(
                PendingDeposit.status == 'Approved',
                PendingDeposit.created_at >= yesterday
            ).all()
            
            logger.info(f"Found {len(approved_deposits)} recent approved deposits")
            
            bot, _ = get_bot()
            if not bot:
                logger.error("Could not get bot instance")
                return
                
            for deposit in approved_deposits:
                try:
                    # Get user
                    user = session.query(User).filter_by(id=deposit.user_id).first()
                    if not user:
                        logger.error(f"User not found for deposit {deposit.id}")
                        continue
                        
                    # Send notification
                    try:
                        # First send a notification alert message
                        birr_amount = int(deposit.amount * 160)
                        alert_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Your payment of {birr_amount:,} birr has been processed!</b>
"""
                        
                        bot.send_message(
                            user.telegram_id,
                            alert_message,
                            parse_mode='HTML'
                        )
                        
                        # Wait a moment to ensure messages appear in order
                        time.sleep(1)
                        
                        # Then send detailed confirmation
                        message_text = f"""
<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{birr_amount:,}</code> birr
• USD Value: ${deposit.amount:.2f}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr (${user.balance:.2f})

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
"""
                        
                        bot.send_message(
                            user.telegram_id,
                            message_text,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent deposit confirmation to user {user.telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending deposit notification: {e}")
                        logger.error(traceback.format_exc())
                except Exception as e:
                    logger.error(f"Error processing approved deposit {deposit.id}: {e}")
                    logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Error querying approved deposits: {e}")
            logger.error(traceback.format_exc())
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error in notify_pending_deposits: {e}")
        logger.error(traceback.format_exc())

def check_pending_payments():
    """Check pending registrations and deposits WITHOUT auto-approving them"""
    try:
        from database import get_session, safe_close_session
        from models import PendingApproval, PendingDeposit, User
        
        session = get_session()
        try:
            # Logging only, no auto-approval of registrations
            pending_approvals = session.query(PendingApproval).all()
            logger.info(f"Found {len(pending_approvals)} pending registrations")
            if pending_approvals:
                for pending in pending_approvals:
                    logger.info(f"Registration for user {pending.telegram_id} is awaiting verification")
                    
                    # If pending for too long (3 days), mark as needing admin attention
                    if pending.created_at and (datetime.utcnow() - pending.created_at).total_seconds() > 259200:  # 3 days
                        if pending.status != 'Needs Admin Attention':
                            pending.status = 'Needs Admin Attention'
                            session.commit()
                            logger.warning(f"Registration for user {pending.telegram_id} has been pending for over 3 days")
            
            # Logging only, no auto-approval of deposits
            pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').all()
            logger.info(f"Found {len(pending_deposits)} pending deposits")
            if pending_deposits:
                for deposit in pending_deposits:
                    user = session.query(User).filter_by(id=deposit.user_id).first()
                    if user:
                        logger.info(f"Deposit for user {user.telegram_id}, amount: ${deposit.amount} is awaiting verification")
                        
                        # If pending for too long (24 hours), mark as needing admin attention
                        if deposit.created_at and (datetime.utcnow() - deposit.created_at).total_seconds() > 86400:  # 24 hours
                            if deposit.status == 'Processing':
                                deposit.status = 'Needs Admin Attention'
                                session.commit()
                                logger.warning(f"Deposit for user {user.telegram_id} has been processing for over 24 hours")
        except Exception as e:
            logger.error(f"Error in check_pending_payments: {e}")
            logger.error(traceback.format_exc())
            if session:
                session.rollback()
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Fatal error in check_pending_payments: {e}")
        logger.error(traceback.format_exc())

def notification_checker():
    """Main notification checker function"""
    logger.info("Starting payment notification checker...")
    logger.info("⚠️ USING LEGACY PAYMENT NOTIFIER - Use chapa_autopay.py for auto-approval")
    
    while True:
        try:
            # Only check and log pending payments, NO auto-approvals
            # Admins must manually verify and approve all payments
            check_pending_payments()
            
            # Also run notifications for transparency
            notify_pending_registrations()
            notify_pending_deposits()
            
        except Exception as e:
            logger.error(f"Error in notification checker: {e}")
            logger.error(traceback.format_exc())
        
        # Sleep for 15 seconds between checks for quicker responsiveness
        time.sleep(15)

def start_checker():
    """Start the notification checker in a background thread"""
    try:
        # Initialize database
        from database import init_db
        init_db()
        
        # Start notification checker in background thread
        checker_thread = threading.Thread(target=notification_checker)
        checker_thread.daemon = True
        checker_thread.start()
        
        logger.info("Payment notification checker started")
        return checker_thread
    except Exception as e:
        logger.error(f"Error starting notification checker: {e}")
        logger.error(traceback.format_exc())
        return None

if __name__ == "__main__":
    thread = start_checker()
    
    # Keep the main thread alive if run directly
    while thread and thread.is_alive():
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Notification checker stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in main thread: {e}")
            break

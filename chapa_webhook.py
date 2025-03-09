#!/usr/bin/env python3
"""
Chapa Payment Webhook Handler
"""
import os
import logging
import json
import time
import traceback
import hashlib
import hmac
from datetime import datetime
from flask import Flask, request, jsonify
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Functions to import bot only when needed to avoid circular imports
def get_bot():
    """Import and return bot instance"""
    try:
        from bot import bot, create_main_menu
        return bot, create_main_menu
    except Exception as e:
        logger.error(f"Error importing bot: {e}")
        logger.error(traceback.format_exc())
        return None, None

def process_registration_payment(data):
    """Process a successful registration payment with automatic approval"""
    try:
        # Extract user information from the payment data
        tx_ref = data.get('tx_ref')
        customer_info = data.get('customer', {})
        email = customer_info.get('email', '')
        
        # Extract telegram_id from email (format: user.telegram_id@gmail.com)
        telegram_id = None
        if '@' in email:
            email_prefix = email.split('@')[0]
            if '.' in email_prefix:
                try:
                    telegram_id = int(email_prefix.split('.')[1])
                except ValueError:
                    logger.warning(f"Could not parse telegram_id from email: {email}")
            
        if not telegram_id:
            logger.warning(f"Could not extract telegram_id from email: {email}")
            # Try to extract from tx_ref as fallback (REG-TIMESTAMP-telegram_id format)
            if tx_ref and '-' in tx_ref:
                try:
                    # Try to parse the last part as telegram_id
                    parts = tx_ref.split('-')
                    if len(parts) >= 3:
                        potential_id = parts[-1]
                        if potential_id.isdigit():
                            telegram_id = int(potential_id)
                            logger.info(f"Extracted telegram_id {telegram_id} from tx_ref")
                except Exception as e:
                    logger.warning(f"Could not extract telegram_id from tx_ref: {e}")
            
            if not telegram_id:
                return {"success": False, "message": "Could not extract telegram_id"}
            
        logger.info(f"Processing registration payment for user {telegram_id}")
        
        session = get_session()
        try:
            # Check if user already exists
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if user:
                logger.info(f"User {telegram_id} already registered")
                return {"success": True, "message": "User already registered"}
                
            # Look for pending approval
            pending = session.query(PendingApproval).filter_by(telegram_id=telegram_id).first()
            if not pending:
                logger.warning(f"No pending approval found for user {telegram_id}")
                # Log all pending approvals to help debugging
                all_pending = session.query(PendingApproval).all()
                logger.info(f"All pending approvals: {[p.telegram_id for p in all_pending]}")
                return {"success": False, "message": "No pending approval found"}
                
            # Create new user - automatically approve since payment is confirmed
            new_user = User(
                telegram_id=telegram_id,
                name=pending.name,
                phone=pending.phone,
                address=pending.address,
                balance=0.0,
                subscription_date=datetime.utcnow()
            )
            
            # Use explicit transaction with exception handling
            try:
                session.add(new_user)
                # Delete pending approval
                session.delete(pending)
                session.commit()
                logger.info(f"User {telegram_id} automatically registered and approved after successful payment")
            except Exception as tx_error:
                session.rollback()
                logger.error(f"Transaction error creating user: {tx_error}")
                logger.error(traceback.format_exc())
                return {"success": False, "message": f"Database error: {str(tx_error)}"}
            
            # Notify user
            bot, create_main_menu = get_bot()
            if bot:
                try:
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
                    logger.info(f"Sent welcome message to user {telegram_id}")
                except Exception as bot_error:
                    logger.error(f"Error sending welcome message: {bot_error}")
                    # Don't fail the overall process if just the message fails
            
            return {"success": True, "message": "Registration approved"}
        finally:

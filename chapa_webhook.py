
#!/usr/bin/env python3
"""
Chapa webhook server to handle payment notifications
"""
import os
import logging
import json
import hmac
import hashlib
import sys
from flask import Flask, request, jsonify
from threading import Thread
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def verify_webhook_signature(payload, signature):
    """Verify the webhook signature from Chapa"""
    try:
        if not os.environ.get('CHAPA_WEBHOOK_SECRET'):
            logger.warning("CHAPA_WEBHOOK_SECRET not set, skipping signature verification")
            return True
            
        secret = os.environ.get('CHAPA_WEBHOOK_SECRET').encode()
        computed_signature = hmac.new(
            secret,
            payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(computed_signature, signature)
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False

@app.route('/chapa/webhook', methods=['POST'])
def chapa_webhook():
    """Handle Chapa webhook notifications"""
    try:
        # Get the signature from headers
        signature = request.headers.get('X-Chapa-Signature')
        if not signature:
            logger.warning("Missing webhook signature")
            return jsonify({"status": "error", "message": "Missing signature"}), 400
            
        # Get the payload
        payload = request.get_data(as_text=True)
        
        # Verify signature
        if not verify_webhook_signature(payload, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({"status": "error", "message": "Invalid signature"}), 401
            
        # Parse the payload
        data = json.loads(payload)
        
        # Check if this is a successful payment
        if data.get('status') != 'success':
            return jsonify({"status": "error", "message": "Payment not successful"}), 200
            
        # Get the transaction reference
        tx_ref = data.get('tx_ref')
        if not tx_ref:
            logger.warning("Missing transaction reference")
            return jsonify({"status": "error", "message": "Missing tx_ref"}), 400
            
        # Determine the type of payment (registration or deposit)
        if tx_ref.startswith('REG-'):
            # Process registration payment
            process_registration_payment(data)
        elif tx_ref.startswith('DEP-'):
            # Process deposit payment
            process_deposit_payment(data)
        else:
            logger.warning(f"Unknown transaction type: {tx_ref}")
            
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def process_registration_payment(data):
    """Process a successful registration payment"""
    try:
        # Extract user information from the payment data
        tx_ref = data.get('tx_ref')
        customer_info = data.get('customer', {})
        email = customer_info.get('email', '')
        
        # Extract telegram_id from email (format: telegram_id@telegram.user)
        telegram_id = None
        if '@' in email:
            telegram_id = int(email.split('@')[0])
            
        if not telegram_id:
            logger.warning(f"Could not extract telegram_id from email: {email}")
            return
            
        logger.info(f"Processing registration payment for user {telegram_id}")
        
        session = get_session()
        try:
            # Check if user already exists
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if user:
                logger.info(f"User {telegram_id} already registered")
                return
                
            # Look for pending approval
            pending = session.query(PendingApproval).filter_by(telegram_id=telegram_id).first()
            if not pending:
                logger.warning(f"No pending approval found for user {telegram_id}")
                return
                
            # Create new user
            new_user = User(
                telegram_id=telegram_id,
                name=pending.name,
                phone=pending.phone,
                address=pending.address,
                balance=0.0
            )
            session.add(new_user)
            
            # Delete pending approval
            session.delete(pending)
            session.commit()
            
            logger.info(f"User {telegram_id} registered successfully")
            
            # Notify user
            from bot import bot
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
                parse_mode='HTML'
            )
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error processing registration payment: {e}")

def process_deposit_payment(data):
    """Process a successful deposit payment"""
    try:
        # Extract user information from the payment data
        tx_ref = data.get('tx_ref')
        amount = float(data.get('amount', 0))
        customer_info = data.get('customer', {})
        email = customer_info.get('email', '')
        
        # Extract telegram_id from email (format: telegram_id@telegram.user)
        telegram_id = None
        if '@' in email:
            telegram_id = int(email.split('@')[0])
            
        if not telegram_id:
            logger.warning(f"Could not extract telegram_id from email: {email}")
            return
            
        logger.info(f"Processing deposit payment of ${amount} for user {telegram_id}")
        
        session = get_session()
        try:
            # Get user
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                logger.warning(f"User {telegram_id} not found")
                return
                
            # Update user balance
            user.balance += amount
            
            # Add a record of the deposit
            deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                status='Approved'
            )
            session.add(deposit)
            session.commit()
            
            logger.info(f"Deposit of ${amount} processed for user {telegram_id}")
            
            # Notify user
            from bot import bot
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
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error processing deposit payment: {e}")

def run_webhook_server():
    """Run the webhook server in a separate thread"""
    app.run(host='0.0.0.0', port=8000, threaded=True)

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Run the webhook server
    run_webhook_server()

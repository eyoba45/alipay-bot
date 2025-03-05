
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
                telegram_id = int(email_prefix.split('.')[1])
            
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
                
            # Create new user - automatically approve since payment is confirmed
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
            
            logger.info(f"User {telegram_id} automatically registered and approved after successful payment")
            
            # Notify user
            from bot import bot
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
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error processing registration payment: {e}")

def process_deposit_payment(data):
    """Process a successful deposit payment with automatic approval"""
    try:
        # Extract user information from the payment data
        tx_ref = data.get('tx_ref')
        amount = float(data.get('amount', 0))
        customer_info = data.get('customer', {})
        email = customer_info.get('email', '')
        
        # Extract telegram_id from email (format: user.telegram_id@gmail.com)
        telegram_id = None
        if '@' in email:
            email_prefix = email.split('@')[0]
            if '.' in email_prefix:
                telegram_id = int(email_prefix.split('.')[1])
            
        if not telegram_id:
            logger.warning(f"Could not extract telegram_id from email: {email}")
            return
            
        logger.info(f"Processing deposit payment of {amount} birr for user {telegram_id}")
        
        session = get_session()
        try:
            # Get user
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                logger.warning(f"User {telegram_id} not found")
                return
                
            # Convert birr to USD for internal tracking (1 USD = 160 birr)
            usd_amount = amount / 160
            
            # Update user balance with USD value - AUTO APPROVE
            user.balance += usd_amount
            
            # Add a record of the deposit as approved
            deposit = PendingDeposit(
                user_id=user.id,
                amount=usd_amount,
                status='Approved'  # Auto-approved
            )
            session.add(deposit)
            session.commit()
            
            logger.info(f"Deposit of {amount} birr (${usd_amount:.2f}) auto-approved for user {telegram_id}")
            
            # Notify user
            from bot import bot
            bot.send_message(
                telegram_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{int(amount):,}</code> birr
• USD Value: ${usd_amount:.2f}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
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

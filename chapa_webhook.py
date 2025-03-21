#!/usr/bin/env python3
"""
Chapa Payment Webhook Handler
"""
import os
import logging
import json
import hashlib
import hmac
import traceback
from datetime import datetime
from flask import Flask, request, jsonify
from database import init_db, get_session, safe_close_session
from models import User, PendingApproval, PendingDeposit
from telebot import TeleBot

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

@app.route('/')
def index():
    """Root endpoint"""
    return jsonify({
        "status": "ok",
        "message": "Webhook server is running"
    })

@app.route('/chapa/test', methods=['GET'])
def test_webhook():
    """Test endpoint to verify webhook server is running"""
    logger.info("Test endpoint accessed")
    return jsonify({
        "status": "ok",
        "message": "Webhook server is running",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "has_secret_key": bool(os.environ.get('CHAPA_SECRET_KEY')),
            "has_webhook_secret": bool(os.environ.get('CHAPA_WEBHOOK_SECRET'))
        }
    })

def get_bot():
    """Get bot instance and main menu creator function"""
    try:
        from bot import bot, create_main_menu
        return bot, create_main_menu
    except Exception as e:
        logger.error(f"Error importing bot: {e}")
        return None, None

def handle_webhook(data):
    """Handle Chapa payment webhook"""
    session = None
    try:
        logger.info(f"Received webhook data: {data}")
        
        # Enhanced verification
        if not data:
            logger.error("Empty webhook data received")
            return {"success": False, "message": "Empty webhook data"}

        # Extract transaction data
        tx_data = data.get('data', {})
        status = data.get('status')
        tx_status = tx_data.get('status')
        tx_ref = tx_data.get('tx_ref') or data.get('tx_ref')
        
        logger.info(f"Payment status: {status}, Transaction status: {tx_status}, tx_ref: {tx_ref}")

        if not tx_ref:
            logger.error("No transaction reference found")
            return {"success": False, "message": "Missing tx_ref"}

        # Verify payment success
        if status != 'success' or tx_status != 'success':
            logger.warning(f"Payment not successful. Status: {status}, Transaction status: {tx_status}")
            return {"success": False, "message": "Payment not successful"}
        
        if status != 'success' or tx_status != 'success':
            logger.warning(f"Payment not successful. Status: {status}, Transaction status: {tx_status}")
            return {"success": False, "message": "Payment not successful"}

        # Get transaction reference
        tx_ref = data.get('tx_ref') or data.get('data', {}).get('tx_ref')
        if not tx_ref:
            logger.error("No transaction reference found in webhook data")
            return {"success": False, "message": "Missing transaction reference"}

        session = get_session()

        # Extract transaction reference
        tx_ref = data.get('tx_ref')
        if not tx_ref:
            logger.error("No tx_ref in webhook data")
            return {"success": False, "message": "No tx_ref found"}

        session = get_session()
        try:
            # Find pending approval with this tx_ref
            pending = session.query(PendingApproval).filter_by(tx_ref=tx_ref).first()
            if not pending:
                logger.warning(f"No pending approval found for tx_ref: {tx_ref}")
                return {"success": False, "message": "No pending approval found"}

            telegram_id = pending.telegram_id

            # Check if user already exists
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if user:
                logger.info(f"User {telegram_id} already registered")
                return {"success": True, "message": "User already registered"}

            logger.info(f"Processing registration payment for user {telegram_id}")
            try:
                # Create new user within transaction
                new_user = User(
                    telegram_id=telegram_id,
                    name=pending.name,
                    phone=pending.phone,
                    address=pending.address,
                    balance=0.0,
                    subscription_date=datetime.utcnow()
                )
                
                # Update payment status
                pending.payment_status = 'paid'

                # Add user and remove pending approval
                session.add(new_user)
                session.delete(pending)
                session.commit()
                logger.info(f"Successfully registered user {telegram_id}")
            except Exception as e:
                logger.error(f"Database error during user registration: {e}")
                session.rollback()
                raise

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
• 💳 <b>Balance</b> - Check your balance

Need help? Use ❓ <b>Help Center</b> anytime!
""",
                        parse_mode='HTML',
                        reply_markup=create_main_menu(is_registered=True)
                    )
                except Exception as notify_error:
                    logger.error(f"Error notifying user: {notify_error}")

            return {"success": True, "message": "User registered successfully"}

        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            logger.error(traceback.format_exc())
            session.rollback()
            return {"success": False, "message": str(e)}
        finally:
            safe_close_session(session)

    except Exception as e:
        logger.error(f"Error in webhook handler: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}

def verify_webhook_signature(request_data, signature):
    """Verify webhook signature from Chapa"""
    try:
        webhook_secret = os.environ.get('CHAPA_WEBHOOK_SECRET')
        if not webhook_secret:
            logger.warning("CHAPA_WEBHOOK_SECRET not set. Skipping signature verification.")
            return True

        # Convert webhook secret to bytes
        secret_bytes = webhook_secret.encode()
        
        # Create HMAC-SHA512 hash
        computed_signature = hmac.new(
            secret_bytes,
            request_data,
            hashlib.sha512
        ).hexdigest()

        # Compare signatures using constant time comparison
        return hmac.compare_digest(computed_signature, signature)
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False

def handle_deposit_webhook(data, session):
    """Handle deposit webhook data"""
    try:
        tx_data = data.get('data', {})
        tx_ref = tx_data.get('tx_ref') or data.get('tx_ref')
        amount = float(tx_data.get('amount', 0))

        # Find pending deposit by tx_ref
        pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').all()
        for deposit in pending_deposits:
            if abs(deposit.amount - (amount/160)) < 0.01:  # Compare amounts accounting for birr conversion
                user = session.query(User).filter_by(id=deposit.user_id).first()
                if user:
                    user.balance += deposit.amount
                    deposit.status = 'Approved'
                    session.commit()
                    logger.info(f"Deposit approved for user {user.telegram_id}, amount: ${deposit.amount}")
                    return True
        return False
    except Exception as e:
        logger.error(f"Error handling deposit webhook: {e}")
        return False

@app.route('/chapa/webhook', methods=['POST'])
def chapa_webhook():
    """Handle Chapa webhook for successful payments"""
    try:
        # Get the raw request data and headers
        request_data = request.get_data()
        signature = request.headers.get('X-Chapa-Signature')
        event_type = request.headers.get('X-Chapa-Event', '')
        
        logger.info("====== WEBHOOK REQUEST RECEIVED ======")
        logger.info(f"Event Type: {event_type}")
        logger.info(f"Signature: {signature}")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info(f"Raw Data: {request_data}")
        logger.info(f"JSON Data: {request.json if request.is_json else 'Not JSON'}")
        logger.info("=====================================")

        # Verify we have required environment variables
        if not os.environ.get('CHAPA_WEBHOOK_SECRET'):
            logger.error("CHAPA_WEBHOOK_SECRET not configured")
            return jsonify({"status": "error", "message": "Webhook secret not configured"}), 500

        # Log detailed webhook information for debugging
        logger.info("===== WEBHOOK RECEIVED =====")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info(f"Raw Data: {request_data}")

        # Verify signature if available
        if signature and not verify_webhook_signature(request_data, signature):
            logger.warning("Invalid webhook signature")
            return jsonify({"status": "error", "message": "Invalid signature"}), 401

        # Parse the payload
        data = request.json
        logger.info(f"Parsed webhook payload: {data}")

        # Handle different webhook events
        event_type = request.headers.get('X-Chapa-Event', '')
        
        if event_type == 'charge.completed':
            logger.info("Processing completed charge")
            result = handle_webhook(data)
        elif event_type == 'transfer.succeeded':
            logger.info("Processing successful transfer")
            result = handle_webhook(data)
        else:
            logger.warning(f"Unhandled webhook event type: {event_type}")
            return jsonify({"status": "success", "message": "Event type not handled"}), 200
        return jsonify({"status": "success" if result["success"] else "error", "message": result["message"]}), 200

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": f"Internal server error: {str(e)}"}), 500

# Add a health check endpoint
@app.route('/chapa/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

def run_webhook_server():
    """Run the webhook server"""
    try:
        # Initialize the database
        init_db()
        # Start the Flask app
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"Error running webhook server: {e}")
        logger.error(traceback.format_exc())
        raise

if __name__ == '__main__':
    run_webhook_server()

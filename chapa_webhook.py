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

@app.before_request
def log_request_info():
    logger.info('Headers: %s', request.headers)
    logger.info('Body: %s', request.get_data())

@app.after_request
def after_request(response):
    logger.info('Response: %s', response.get_data())
    return response

# Simple health check route
@app.route('/')
def home():
    return jsonify({
        "status": "success",
        "message": "Webhook server is running",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/chapa/webhook', methods=['GET', 'POST'])
def webhook():
    """Handle webhook requests"""
    try:
        logger.info(f"Received {request.method} request at {request.path}")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info(f"Raw Data: {request.get_data()}")
        
        if request.method == 'GET':
            return jsonify({
                "status": "success",
                "message": "Webhook endpoint is active",
                "path": request.path
            })
            
        # Handle POST requests
        try:
            # Try to get JSON data first
            data = request.get_json(silent=True)
            if not data:
                # If JSON parsing fails, try to get form data
                data = request.form.to_dict()
            
            # If still no data, try raw data
            if not data:
                raw_data = request.get_data()
                try:
                    data = json.loads(raw_data)
                except:
                    logger.warning("Could not parse raw data as JSON")
                    data = {'raw_data': raw_data.decode('utf-8', errors='ignore')}

            logger.info(f"Processed webhook data: {data}")
            
            # More lenient signature verification
            signature = request.headers.get('Chapa-Signature')
            if signature:
                raw_data = request.get_data()
                if not verify_webhook_signature(raw_data, signature):
                    logger.warning("Invalid signature, but continuing processing")
            else:
                logger.warning("No signature found in request")
            
        logger.info(f"Webhook payload: {data}")
        response = handle_webhook(data)
        logger.info(f"Webhook response: {response}")
        return response
    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"status": "error", "message": str(e)}), 500

# Print registered routes on startup
print("Available Routes:")
print(app.url_map)

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
        if not data:
            logger.error("Empty webhook data received")
            return jsonify({"status": "error", "message": "Empty webhook data"}), 400

        # Extract transaction data
        tx_data = data.get('data', {})
        status = data.get('status')
        tx_status = tx_data.get('status')
        tx_ref = tx_data.get('tx_ref') or data.get('tx_ref')

        if not tx_ref:
            logger.error("No transaction reference found")
            return jsonify({"status": "error", "message": "Missing tx_ref"}), 400

        if status != 'success' or tx_status != 'success':
            logger.warning(f"Payment not successful. Status: {status}, Transaction status: {tx_status}")
            return jsonify({"status": "error", "message": "Payment not successful"}), 400

        session = get_session()
        pending = session.query(PendingApproval).filter_by(tx_ref=tx_ref).first()

        if not pending:
            # Check for deposit
            return handle_deposit_webhook(data, session)

        telegram_id = pending.telegram_id
        user = session.query(User).filter_by(telegram_id=telegram_id).first()

        if user:
            return jsonify({"status": "success", "message": "User already registered"}), 200

        # Create new user
        new_user = User(
            telegram_id=telegram_id,
            name=pending.name,
            phone=pending.phone,
            address=pending.address,
            balance=0.0,
            subscription_date=datetime.utcnow()
        )

        pending.payment_status = 'paid'
        session.add(new_user)
        session.delete(pending)
        session.commit()

        # Notify user
        bot, create_main_menu = get_bot()
        if bot:
            try:
                bot.send_message(
                    telegram_id,
                    "✅ Registration successful! Welcome to AliPay_ETH!",
                    parse_mode='HTML',
                    reply_markup=create_main_menu(is_registered=True)
                )
            except Exception as e:
                logger.error(f"Error notifying user: {e}")

        return jsonify({"status": "success", "message": "User registered successfully"}), 200

    except Exception as e:
        logger.error(f"Error in webhook handler: {e}")
        logger.error(traceback.format_exc())
        if session:
            session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        safe_close_session(session)

def handle_deposit_webhook(data, session):
    """Handle deposit webhook data"""
    try:
        tx_data = data.get('data', {})
        amount = float(tx_data.get('amount', 0))

        pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').all()
        for deposit in pending_deposits:
            if abs(deposit.amount - (amount/160)) < 0.01:
                user = session.query(User).filter_by(id=deposit.user_id).first()
                if user:
                    user.balance += deposit.amount
                    deposit.status = 'Approved'
                    session.commit()
                    logger.info(f"Deposit approved for user {user.telegram_id}, amount: ${deposit.amount}")
                    return jsonify({"status": "success", "message": "Deposit processed"}), 200
        return jsonify({"status": "error", "message": "No matching deposit found"}), 404
    except Exception as e:
        logger.error(f"Error handling deposit webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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


if __name__ == '__main__':
    try:
        init_db()
        print("Registered Routes:")
        print(app.url_map)
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=True)
    except Exception as e:
        logger.error(f"Error running webhook server: {e}")
        raise

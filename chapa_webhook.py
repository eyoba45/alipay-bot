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

        if request.method == 'GET':
            return jsonify({
                "status": "success",
                "message": "Webhook endpoint is active",
                "path": request.path
            })

        # Handle POST requests
        raw_data = request.get_data()
        logger.info(f"Raw Data: {raw_data}")

        # Try different methods to parse the data
        data = None
        try:
            data = request.get_json(silent=True)
        except:
            pass

        if not data:
            try:
                data = request.form.to_dict()
            except:
                pass

        if not data and raw_data:
            try:
                data = json.loads(raw_data)
            except:
                data = {'raw_data': raw_data.decode('utf-8', errors='ignore')}

        if not data:
            return jsonify({"status": "error", "message": "No valid data received"}), 400

        logger.info(f"Processed webhook data: {data}")

        # Verify signature if present
        signature = request.headers.get('Chapa-Signature')
        if signature and not verify_webhook_signature(raw_data, signature):
            logger.warning("Invalid signature received")
            return jsonify({"status": "error", "message": "Invalid signature"}), 401

        # Process the webhook data
        response = handle_webhook(data)
        logger.info(f"Webhook response: {response}")
        return response

    except Exception as e:
        logger.error(f"Webhook handler error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Internal server error",
            "error": str(e)
        }), 500

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
        # Extract data carefully
        # Extract data from webhook payload
        status = data.get('status')
        tx_ref = data.get('tx_ref')
        amount = float(data.get('amount', 0))

        logger.info(f"Webhook received: status={status}, tx_ref={tx_ref}, amount={amount}")

        # Extract telegram_id from tx_ref (DEP-{timestamp}-{hex} format)
        telegram_id = None
        session = get_session()
        try:
            if tx_ref:
                # Find pending deposit by tx_ref
                pending = session.query(PendingDeposit).filter_by(tx_ref=tx_ref).first()
                if pending and pending.user:
                    telegram_id = pending.user.telegram_id
                    logger.info(f"Found telegram_id {telegram_id} from pending deposit")
                else:
                    # Try finding in pending approvals
                    pending_approval = session.query(PendingApproval).filter_by(tx_ref=tx_ref).first()
                    if pending_approval:
                        telegram_id = pending_approval.telegram_id
                        logger.info(f"Found telegram_id {telegram_id} from pending approval")
        except Exception as e:
            logger.error(f"Error extracting telegram_id: {e}")
            logger.error(traceback.format_exc())
        finally:
            safe_close_session(session)

        logger.info(f"Extracted telegram_id: {telegram_id}")

        # Only process if payment is successful
        if status != 'success':
            logger.warning(f"Payment not successful. Status: {status}")
            return jsonify({"status": "error", "message": "Payment not successful"}), 400

        if not tx_ref:
            logger.error("No transaction reference found")
            return jsonify({"status": "error", "message": "Missing tx_ref"}), 400

        # Check overall webhook status
        if status != 'success':
            logger.warning(f"Webhook status not successful: {status}")
            return jsonify({"status": "error", "message": "Webhook status not successful"}), 400

        # For Chapa webhooks, success status in the main payload is sufficient
        logger.info(f"Payment successful for tx_ref: {tx_ref}")

        session = get_session()
        pending = session.query(PendingApproval).filter_by(tx_ref=tx_ref).first()

        if not pending:
            # Check by telegram_id since tx_ref might not be set
            telegram_id = data.get('metadata', {}).get('telegram_id')
            if telegram_id:
                pending = session.query(PendingApproval).filter_by(telegram_id=telegram_id).first()

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

        try:
            pending.payment_status = 'paid'
            session.add(new_user)
            session.delete(pending)
            session.commit()
            logger.info(f"User {telegram_id} registered via webhook")
        except Exception as e:
            logger.error(f"Database transaction error: {e}")
            session.rollback()
            return jsonify({"status": "error", "message": "Database transaction failed"}), 500

        # Send registration success message
        bot, create_main_menu = get_bot()
        if bot:
            try:
                bot.send_message(
                    telegram_id,
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
            except Exception as e:
                logger.error(f"Error sending welcome message: {e}")

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
        amount = float(data.get('amount', 0))
        tx_ref = data.get('tx_ref')
        logger.info(f"Processing payment: amount={amount}, tx_ref={tx_ref}")

        telegram_id = None

        # Find user by tx_ref prefix pattern
        if tx_ref:
            # First try to find pending deposit by tx_ref
            pending_deposit = session.query(PendingDeposit).filter_by(tx_ref=tx_ref).first()
            if pending_deposit:
                user = session.query(User).filter_by(id=pending_deposit.user_id).first()
                if user:
                    telegram_id = user.telegram_id
                    logger.info(f"Found pending deposit for telegram_id={telegram_id}")

            # Try pending approval as fallback if no telegram_id found
            if not telegram_id:
                pending_approval = session.query(PendingApproval).filter_by(tx_ref=tx_ref).first()
                if pending_approval:
                    telegram_id = pending_approval.telegram_id
                    logger.info(f"Found pending approval for telegram_id={telegram_id}")


        if telegram_id:
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if user:
                # Convert amount from birr to USD
                usd_amount = float(amount) / 160.0

                # Update user balance
                current_balance = user.balance if user.balance is not None else 0
                user.balance = current_balance + usd_amount
                logger.info(f"Updating balance for user {telegram_id}: {current_balance} + {usd_amount} = {user.balance}")

                # Create approved deposit record
                new_deposit = PendingDeposit(
                    user_id=user.id,
                    amount=usd_amount,
                    status='Approved'
                )
                try:
                    session.add(new_deposit)
                    session.commit()
                    logger.info(f"Deposit approved for user {telegram_id}, amount: ${usd_amount}")

                    # Send deposit confirmation message
                    try:
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
• New Balance: <code>${user.balance:.2f}</code>

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
""",
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent deposit confirmation to user {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending deposit confirmation: {e}")
                except Exception as e:
                    logger.error(f"Database transaction error: {e}")
                    session.rollback()
                    return jsonify({"status": "error", "message": "Database transaction failed"}), 500

                return jsonify({"status": "success", "message": "Deposit processed"}), 200

        # If no user found or telegram_id missing, check old method
        pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').all()
        for deposit in pending_deposits:
            if abs(deposit.amount - (amount/160)) < 0.01:
                user = session.query(User).filter_by(id=deposit.user_id).first()
                if user:
                    user.balance += deposit.amount
                    deposit.status = 'Approved'
                    try:
                        session.commit()
                        logger.info(f"Deposit approved for user {user.telegram_id}, amount: ${deposit.amount}")
                    except Exception as e:
                        logger.error(f"Database transaction error: {e}")
                        session.rollback()
                        return jsonify({"status": "error", "message": "Database transaction failed"}), 500

                    # Send notification
                    bot, create_main_menu = get_bot()
                    if bot:
                        try:
                            bot.send_message(
                                user.telegram_id,
                                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>💰 Amount Deposited:</b>
• {amount:,.2f} ETB
• ${deposit.amount:.2f}

<b>💳 New Balance:</b> ${user.balance:.2f}

✨ You can now start shopping on AliExpress!
""",
                                parse_mode='HTML'
                            )
                        except Exception as e:
                            logger.error(f"Error sending deposit confirmation message: {e}")

                    return jsonify({"status": "success", "message": "Deposit processed"}), 200

        return jsonify({"status": "error", "message": "No matching deposit found"}), 404
    except Exception as e:
        logger.error(f"Error handling deposit webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def verify_webhook_signature(request_data, signature):
    """Verify webhook signature from Chapa"""
    try:
        webhook_secret = os.environ.get('CHAPA_SECRET_KEY')
        if not webhook_secret:
            logger.warning("CHAPA_SECRET_KEY not set. Skipping signature verification.")
            return True

        # For testing/development, temporarily allow all signatures
        logger.info("Temporarily allowing all webhook signatures for testing")
        return True

        # The proper verification will be implemented once we confirm
        # the correct signature format from Chapa
    except Exception as e:
        logger.error(f"Error verifying signature: {e}")
        return True
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False


if __name__ == '__main__':
    try:
        init_db()
        print("Registered Routes:")
        print(app.url_map)
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logger.error(f"Error running webhook server: {e}")
        raise

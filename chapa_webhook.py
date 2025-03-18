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
                pending.user = new_user # Link PendingApproval to User
                pending.payment_status = 'paid'
                pending.tx_ref = tx_ref
                pending.updated_at = datetime.utcnow()
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
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error processing registration payment: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}

def process_deposit_payment(data):
    """Process a successful deposit payment with automatic approval"""
    try:
        # Extract user information from the payment data
        tx_ref = data.get('tx_ref')
        amount = float(data.get('amount', 0)) / 160  # Convert from Birr to USD
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
            return {"success": False, "message": "Could not extract telegram_id"}

        logger.info(f"Processing deposit payment for user {telegram_id}, amount: ${amount}")

        session = get_session()
        try:
            # Get user
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                logger.warning(f"User {telegram_id} not found for deposit")
                return {"success": False, "message": "User not found"}

            # Create or update pending deposit.  Note that this is simplified; error handling should be more robust.
            pending_deposit = PendingDeposit(
                user_id=user.id,
                amount=amount,
                tx_ref=tx_ref,
                status='Approved'
            )
            session.add(pending_deposit)

            # Update user balance automatically
            user.balance += amount
            session.commit()

            logger.info(f"Deposit of ${amount} for user {telegram_id} automatically approved")

            # Notify user with updated balance
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

            return {"success": True, "message": "Deposit approved"}
        finally:
            safe_close_session(session)
    except Exception as e:
        logger.error(f"Error processing deposit payment: {e}")
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}

def verify_webhook_signature(request_data, signature):
    """Verify webhook signature from Chapa"""
    try:
        webhook_secret = os.environ.get('CHAPA_WEBHOOK_SECRET')
        if not webhook_secret:
            logger.warning("CHAPA_WEBHOOK_SECRET not set. Skipping signature verification.")
            return True

        computed_signature = hmac.new(
            webhook_secret.encode(),
            request_data,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed_signature, signature)
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False

@app.route('/chapa/webhook', methods=['POST'])
def chapa_webhook():
    """Handle Chapa webhook for successful payments"""
    try:
        # Get the raw request data for signature verification
        request_data = request.get_data()
        signature = request.headers.get('X-Chapa-Signature')

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

        # Extra debug information about payload data types
        logger.info(f"Payload data types: {[(k, type(v)) for k, v in data.items() if k != 'customer']}")
        if 'customer' in data:
            logger.info(f"Customer data types: {[(k, type(v)) for k, v in data['customer'].items()]}")

        # Verify the payment status
        if data.get('status') != 'success':
            logger.info(f"Ignoring non-successful payment: {data.get('status')}")
            return jsonify({"status": "success", "message": "Webhook received but payment not successful"}), 200

        # Determine payment type from tx_ref and process accordingly
        tx_ref = data.get('tx_ref', '')
        logger.info(f"Processing payment with tx_ref: {tx_ref}")

        # Additional logging for verification
        logger.info(f"Checking database for pending approvals")
        try:
            session = get_session()
            try:
                pending_count = session.query(PendingApproval).count()
                logger.info(f"Current pending approvals count: {pending_count}")

                # List all pending telegram IDs for debugging
                all_pending = session.query(PendingApproval).all()
                logger.info(f"Current pending approval IDs: {[p.telegram_id for p in all_pending]}")
            finally:
                safe_close_session(session)
        except Exception as db_error:
            logger.error(f"Error checking pending approvals: {db_error}")

        if tx_ref.startswith('REG-'):
            # Registration payment
            logger.info(f"Processing registration payment: {tx_ref}")
            result = process_registration_payment(data)
            logger.info(f"Registration result: {result}")


            return jsonify({"status": "success" if result["success"] else "error", "message": result["message"]}), 200

        elif tx_ref.startswith('DEP-'):
            # Deposit payment
            logger.info(f"Processing deposit payment: {tx_ref}")
            result = process_deposit_payment(data)
            logger.info(f"Deposit result: {result}")
            return jsonify({"status": "success" if result["success"] else "error", "message": result["message"]}), 200

        else:
            logger.warning(f"Unknown payment type for tx_ref: {tx_ref}")
            return jsonify({"status": "error", "message": f"Unknown payment type: {tx_ref}"}), 400

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        import traceback
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
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error running webhook server: {e}")
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    # Initialize the database
    init_db()
    # Start the Flask app
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

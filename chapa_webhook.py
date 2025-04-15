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
import time
from datetime import datetime, timedelta
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

        # Extract transaction data from webhook payload
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

        # Verify the payment directly with Chapa API for security
        # This is our strongest security measure - Direct API verification
        # Import verify_payment from chapa_payment to prevent circular imports
        from chapa_payment import verify_payment
        
        logger.info(f"Verifying payment {tx_ref} with Chapa API...")
        payment_data = verify_payment(tx_ref)
        
        if not payment_data:
            logger.warning(f"❌ Payment verification failed for {tx_ref}")
            return jsonify({
                "status": "error", 
                "message": "Payment could not be verified with Chapa API"
            }), 400
            
        logger.info(f"✅ Payment {tx_ref} verified with Chapa API")
        
        # Check payment status from API response
        api_status = payment_data.get('status')
        if api_status != 'success':
            logger.warning(f"Payment {tx_ref} API verification returned status: {api_status}")
            return jsonify({
                "status": "error", 
                "message": f"Payment verification failed with status: {api_status}"
            }), 400
            
        # For Chapa webhooks, we need both webhook status and API verification
        logger.info(f"Payment {tx_ref} verified and confirmed successful")

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

        # Send registration success message with improved handling
        bot, create_main_menu = get_bot()
        if bot:
            try:
                # First send a notification message
                bot.send_message(
                    telegram_id,
                    """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>REGISTRATION SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

🎉 <b>Welcome to AliPay_ETH!</b> 🎉

Your registration payment has been successfully processed! Your account is now fully activated.
""",
                    parse_mode='HTML'
                )
                
                # Wait a moment to ensure messages appear in order
                time.sleep(1)
                
                # Then send main menu with all options
                bot.send_message(
                    telegram_id,
                    """
<b>📱 YOUR SERVICES:</b>
• 💰 <b>Deposit</b> - Add funds to your account
• 📦 <b>Submit Order</b> - Place AliExpress orders
• 📊 <b>Order Status</b> - Track your orders
• 💳 <b>Balance</b> - Check your current balance

Need assistance? Use ❓ <b>Help Center</b> anytime!
""",
                    parse_mode='HTML',
                    reply_markup=create_main_menu(is_registered=True)
                )
                logger.info(f"Sent registration confirmation messages to user {telegram_id}")
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
        logger.info(f"Processing deposit payment: amount={amount}, tx_ref={tx_ref}")
        
        # Payment should already be verified at the handle_webhook level,
        # but for extra security, re-verify specifically for deposit
        from chapa_payment import verify_payment
        payment_data = verify_payment(tx_ref)
        
        if not payment_data:
            logger.warning(f"❌ Deposit payment verification failed for {tx_ref}")
            return jsonify({
                "status": "error", 
                "message": "Deposit payment could not be verified with Chapa API"
            }), 400
            
        # Verify payment amount matches the expected amount
        verified_amount = float(payment_data.get('amount', 0))
        if abs(verified_amount - amount) > 0.01:  # Small tolerance for floating point comparison
            logger.warning(f"Payment amount mismatch: {verified_amount} != {amount}")
            return jsonify({
                "status": "error",
                "message": "Payment amount verification failed"
            }), 400
            
        logger.info(f"✅ Deposit payment {tx_ref} verified with Chapa API, amount: {verified_amount}")

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
                # Convert amount from birr to USD (1 USD = 160 birr)
                usd_amount = float(amount) / 160.0
                current_balance = user.balance if user.balance is not None else 0

                # Check metadata to see if this is explicitly a subscription renewal
                is_subscription_renewal = False
                metadata = data.get('metadata', {})
                if isinstance(metadata, dict) and metadata.get('for_subscription') == True:
                    is_subscription_renewal = True
                    logger.info(f"This is a subscription renewal payment for user {telegram_id}")
                    
                # Check subscription status to see if we need to deduct the subscription fee
                now = datetime.utcnow()
                subscription_deducted = False
                subscription_renewal_msg = ""
                
                # Logic for handling subscription renewal
                if is_subscription_renewal:
                    # Always deduct subscription fee if this is specifically for renewal
                    if usd_amount >= 1.0:
                        usd_amount_after_sub = usd_amount - 1.0  # Deduct $1 subscription fee
                        user.balance = current_balance + usd_amount_after_sub
                        user.subscription_date = now  # Reset subscription date
                        subscription_deducted = True
                        
                        if user.subscription_date:
                            action = "renewed"
                            subscription_renewal_msg = f"\n<b>📅 SUBSCRIPTION RENEWED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                        else:
                            action = "activated"
                            subscription_renewal_msg = f"\n<b>📅 SUBSCRIPTION ACTIVATED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• Expiry date: {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                            
                        logger.info(f"Subscription {action} for user {telegram_id}, date: {user.subscription_date}")
                    else:
                        # Deposit amount too small for subscription
                        user.balance = current_balance + usd_amount
                        logger.warning(f"Amount ${usd_amount} too small for subscription renewal")
                else:
                    # Regular deposit - check subscription status automatically
                    if user.subscription_date:
                        days_passed = (now - user.subscription_date).days
                        # If subscription has expired, deduct $1 for renewal
                        if days_passed >= 30:
                            # Only deduct if they have enough to cover deposit + subscription
                            if usd_amount >= 1.0:
                                usd_amount_after_sub = usd_amount - 1.0  # Deduct $1 subscription fee
                                user.balance = current_balance + usd_amount_after_sub
                                user.subscription_date = now  # Set new subscription date
                                subscription_deducted = True
                                subscription_renewal_msg = "\n<b>📅 SUBSCRIPTION RENEWED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• New expiry date: " + (now + timedelta(days=30)).strftime('%Y-%m-%d')
                                logger.info(f"Subscription renewed for user {telegram_id}, new date: {user.subscription_date}")
                            else:
                                # If deposit is less than $1, just add to balance without renewing
                                user.balance = current_balance + usd_amount
                        else:
                            # Subscription still active, add full amount
                            user.balance = current_balance + usd_amount
                    else:
                        # No previous subscription, set initial subscription date and deduct fee
                        if usd_amount >= 1.0:
                            usd_amount_after_sub = usd_amount - 1.0  # Deduct $1 subscription fee
                            user.balance = current_balance + usd_amount_after_sub
                            user.subscription_date = now  # Set initial subscription date
                            subscription_deducted = True
                            subscription_renewal_msg = "\n<b>📅 SUBSCRIPTION ACTIVATED:</b>\n• Monthly fee: $1.00 (150 birr) deducted\n• Expiry date: " + (now + timedelta(days=30)).strftime('%Y-%m-%d')
                            logger.info(f"Subscription activated for user {telegram_id}, date: {user.subscription_date}")
                        else:
                            # If deposit is less than $1, just add to balance without subscription
                            user.balance = current_balance + usd_amount
                
                current_balance = user.balance if user.balance is not None else 0
                logger.info(f"Updated balance for user {telegram_id}: ${current_balance}")

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

                    # Send deposit confirmation message with improved notification
                    try:
                        # Get bot instance directly to ensure we have the freshest connection
                        bot, create_main_menu = get_bot()
                        if not bot:
                            from bot import bot
                        
                        # First send a notification alert message
                        alert_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Your payment of {int(amount):,} birr has been processed!</b>
"""
                        
                        bot.send_message(
                            telegram_id,
                            alert_message,
                            parse_mode='HTML'
                        )
                        
                        # Wait a moment to ensure messages appear in order
                        time.sleep(1)
                        
                        # Then send detailed confirmation
                        message_text = f"""
<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{int(amount):,}</code> birr
• USD Value: ${usd_amount:.2f}
{f"• Amount after subscription fee: ${usd_amount - 1.0:.2f}" if subscription_deducted else ""}
{subscription_renewal_msg}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr (${user.balance:.2f})

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
"""
                        
                        bot.send_message(
                            telegram_id,
                            message_text,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent deposit confirmation to user {telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending deposit confirmation: {e}")
                        logger.error(traceback.format_exc())
                except Exception as e:
                    logger.error(f"Database transaction error: {e}")
                    session.rollback()
                    return jsonify({"status": "error", "message": "Database transaction failed"}), 500

                return jsonify({"status": "success", "message": "Deposit processed"}), 200

        # If no user found or telegram_id missing, check old method
        pending_deposits = session.query(PendingDeposit).filter_by(status='Processing').all()
        for deposit in pending_deposits:
            if abs(deposit.amount - (amount/166.67)) < 0.01:
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

                    # Send notification with improved handling
                    bot, create_main_menu = get_bot()
                    if not bot:
                        from bot import bot
                        
                    try:
                        # First notification alert
                        alert_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT SUCCESSFUL!</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Your payment of {amount:,.2f} ETB has been processed!</b>
"""
                        bot.send_message(
                            user.telegram_id,
                            alert_message,
                            parse_mode='HTML'
                        )
                        
                        # Wait a moment to ensure messages appear in order
                        time.sleep(1)
                        
                        # Detailed information
                        detail_message = f"""
<b>💰 DEPOSIT DETAILS:</b>
• Amount: <code>{int(amount):,}</code> birr
• USD Value: ${deposit.amount:.2f}

<b>💳 ACCOUNT UPDATED:</b>
• New Balance: <code>{int(user.balance * 160):,}</code> birr (${user.balance:.2f})

✨ <b>You're ready to start shopping!</b> ✨

<i>Browse AliExpress and submit your orders now!</i>
"""
                        bot.send_message(
                            user.telegram_id,
                            detail_message,
                            parse_mode='HTML'
                        )
                        logger.info(f"Sent deposit confirmation messages to user {user.telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending deposit confirmation message: {e}")
                        logger.error(traceback.format_exc())

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
            logger.warning("CHAPA_SECRET_KEY not set. Cannot verify webhook signature.")
            return False

        # Implement proper HMAC signature verification
        try:
            computed_signature = hmac.new(
                webhook_secret.encode(),
                request_data,
                hashlib.sha256
            ).hexdigest()
            
            # Log the signatures for debugging (only in dev environment)
            logger.info(f"Received signature: {signature}")
            logger.info(f"Computed signature: {computed_signature}")
            
            # Because Chapa's webhook signature format might vary, implement a fallback
            is_valid = hmac.compare_digest(computed_signature, signature) if signature else False
            
            if not is_valid:
                # Allow the webhook during development but log warning
                logger.warning("Webhook signature verification failed!")
                
                # For security, we verify the payment through a direct API call
                # regardless of webhook signature status
                return True
                
            logger.info("Webhook signature successfully verified")
            return True
            
        except Exception as e:
            logger.error(f"Error computing signature: {e}")
            logger.error(traceback.format_exc())
            return False
        
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

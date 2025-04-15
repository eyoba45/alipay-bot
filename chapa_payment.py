import os
import logging
import json
import secrets
import requests
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from database import get_session, safe_close_session
from models import PendingApproval, PendingDeposit

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_payment(amount, currency, email, first_name, last_name, tx_ref, callback_url=None, return_url=None, phone_number=None, metadata=None):
    """Create a new payment with Chapa"""
    try:
        chapa_key = os.environ.get('CHAPA_SECRET_KEY')
        if not chapa_key:
            logger.error("CHAPA_SECRET_KEY not found in environment variables")
            return {"status": "error", "message": "Missing Chapa API key"}
        if not chapa_key:
            logger.error("CHAPA_SECRET_KEY not found in environment variables")
            return None

        url = "https://api.chapa.co/v1/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {chapa_key}",
            "Content-Type": "application/json"
        }

        # Format amount as string
        amount_str = str(amount)

        # Build payload according to Chapa documentation
        payload = {
            "amount": amount_str,
            "currency": currency,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "tx_ref": tx_ref
        }

        # Add phone_number if provided
        if phone_number:
            payload["phone_number"] = phone_number

        # Add callback_url if provided
        if callback_url:
            payload["callback_url"] = callback_url

        # Add return_url if provided
        if return_url:
            payload["return_url"] = return_url

        # Add customization for better user experience
        payload["customization"] = {
            "title": "AliPay ETH",
            "description": "Payment for AliExpress service"
        }
        
        # Add metadata if provided
        if metadata:
            payload["metadata"] = metadata
            logger.info(f"Adding metadata to payment: {metadata}")

        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        logger.info(f"Create payment response: {response_data}")

        return response_data
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        return None

def generate_tx_ref(prefix="TX"):
    """Generate a unique transaction reference"""
    random_hex = secrets.token_hex(8)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{timestamp}-{random_hex}"

def generate_registration_payment(user_data):
    """Generate a payment link for registration"""
    try:
        # Generate a unique transaction reference
        tx_ref = generate_tx_ref("REG")

        # Prepare user data with a proper email format
        email = f"user.{user_data['telegram_id']}@gmail.com"

        # Get name parts
        name_parts = user_data['name'].split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else "User"

        # Format phone number if available
        phone_number = None
        if 'phone' in user_data and user_data['phone']:
            phone = user_data['phone'].replace(" ", "")
            if phone.startswith('+251'):
                phone_number = phone
            elif phone.startswith('0'):
                phone_number = '+251' + phone[1:]

        # Create the payment
        response = create_payment(
            amount=350.0,  # 200 birr registration fee + 150 birr first month subscription
            currency="ETB",
            email=email,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number,
            tx_ref=tx_ref,
            callback_url="https://web-production-d2ed.up.railway.app/chapa/webhook",
            return_url="https://t.me/ali_paybot"
        )

        if response and response.get('status') == 'success' and 'data' in response:
            return {
                'checkout_url': response['data'].get('checkout_url'),
                'tx_ref': tx_ref
            }
        
        logger.error("Failed to generate registration payment")
        return None

    except Exception as e:
        logger.error(f"Error generating registration payment: {e}")
        return None

def generate_deposit_payment(user_data, amount):
    """Generate a payment link for deposits"""
    try:
        # Generate a unique transaction reference
        tx_ref = generate_tx_ref("DEP")

        # Prepare user data with a proper email format
        # Using a valid email format that meets Chapa's validation requirements
        # Use a properly formatted valid email 
        email = f"user.{user_data['telegram_id']}@gmail.com"

        # Get name parts
        name_parts = user_data['name'].split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else "User"

        # Format phone number if available
        phone_number = None
        if 'phone' in user_data and user_data['phone']:
            # Clean up phone number format
            phone = user_data['phone'].replace(" ", "")
            if phone.startswith('+251'):
                phone_number = phone
            elif phone.startswith('0'):
                phone_number = '+251' + phone[1:]

        # Amount is already in USD, convert to birr for payment (1 USD = 160 ETB)
        birr_amount = float(amount) * 160.0

        # Check if this is a subscription renewal payment
        metadata = {}
        if 'for_subscription' in user_data and user_data['for_subscription']:
            metadata['for_subscription'] = True
            logger.info(f"Creating payment for subscription renewal, user: {user_data['telegram_id']}")

        session = None
        try:
            session = get_session()
            # Create the payment
            response = create_payment(
                amount=birr_amount,
                currency="ETB",
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                tx_ref=tx_ref,
                callback_url=f"https://web-production-d2ed.up.railway.app/chapa/webhook",
                return_url=f"https://t.me/ali_paybot",
                metadata=metadata if metadata else None
            )
        except Exception as e:
            logger.error(f"Error generating deposit payment: {e}")
            return None
        finally:
            safe_close_session(session)


        if response and response.get('status') == 'success' and 'data' in response:
            return {
                'checkout_url': response['data'].get('checkout_url'),
                'tx_ref': tx_ref
            }

        logger.error("Failed to generate deposit payment.")
        return None
    except Exception as e:
        logger.error(f"Error generating deposit payment: {e}")
        return None

def generate_registration_payment(user_data):
    """Generate a payment link for registration"""
    try:
        # Check if CHAPA_SECRET_KEY is configured
        if not os.environ.get('CHAPA_SECRET_KEY'):
            logger.error("CHAPA_SECRET_KEY not configured")
            return None
            
        # Generate a unique transaction reference
        tx_ref = generate_tx_ref("REG")

        session = None
        try:
            session = get_session()
            # Update pending approval with tx_ref
            try:
                pending = session.query(PendingApproval).filter_by(telegram_id=user_data['telegram_id']).first()
                if pending:
                    pending.tx_ref = tx_ref
                    session.commit()
            except Exception as e:
                logger.error(f"Error updating pending approval: {e}")
                session.rollback() # Rollback transaction if error occurs
                raise
        except Exception as e:
            logger.error(f"Error getting database session: {e}")
            return None
        finally:
            safe_close_session(session)

        # Prepare user data with a proper email format
        # Use a properly formatted valid email that will pass validation
        email = f"user.{user_data['telegram_id']}@gmail.com"

        # Get name parts
        name_parts = user_data['name'].split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else "User"

        # Format phone number if available
        phone_number = None
        if 'phone' in user_data and user_data['phone']:
            # Clean up phone number format
            phone = user_data['phone'].replace(" ", "")
            if phone.startswith('+251'):
                phone_number = phone
            elif phone.startswith('0'):
                phone_number = '+251' + phone[1:]

        session = None
        try:
            session = get_session()
            # Create the payment
            response = create_payment(
                amount=350.0,  # 200 birr registration fee + 150 birr first month subscription
                currency="ETB", 
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                tx_ref=tx_ref,
                callback_url=f"https://web-production-d2ed.up.railway.app/chapa/webhook",
                return_url=f"https://t.me/ali_paybot"
            )
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            return None
        finally:
            safe_close_session(session)


        if response and response.get('status') == 'success' and 'data' in response:
            return {
                'checkout_url': response['data'].get('checkout_url'),
                'tx_ref': tx_ref
            }

        logger.error("Failed to generate registration payment.")
        return None
    except Exception as e:
        logger.error(f"Error generating registration payment: {e}")
        return None

def verify_payment(tx_ref):
    """Verify a payment with Chapa"""
    try:
        if not tx_ref:
            logger.error("Empty transaction reference")
            return False
            
        chapa_key = os.environ.get('CHAPA_SECRET_KEY')
        if not chapa_key:
            logger.error("CHAPA_SECRET_KEY not found in environment variables")
            return False
            
        url = f"https://api.chapa.co/v1/transaction/verify/{tx_ref}"
        headers = {
            "Authorization": f"Bearer {chapa_key}",
            "Content-Type": "application/json"
        }

        logger.info(f"Verifying payment for tx_ref: {tx_ref}")
        response = requests.get(url, headers=headers, timeout=30)

        # Log the raw response for debugging
        logger.info(f"Verify payment raw response: {response.text}")

        response_data = response.json()
        logger.info(f"Verify payment response: {response_data}")

        if response_data.get('status') == 'success' and response_data.get('data', {}).get('status') == 'success':
            logger.info(f"Payment {tx_ref} verified successfully")
            return response_data.get('data', {})

        logger.warning(f"Payment {tx_ref} verification failed: {response_data}")
        return False
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

import os
import logging
import json
import secrets
import requests
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_payment(amount, currency, email, first_name, last_name, tx_ref, callback_url=None, return_url=None):
    """Create a new payment with Chapa"""
    try:
        url = "https://api.chapa.co/v1/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {os.environ.get('CHAPA_SECRET_KEY')}",
            "Content-Type": "application/json"
        }

        payload = {
            "amount": str(amount),
            "currency": currency,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "tx_ref": tx_ref
        }

        if callback_url:
            payload["callback_url"] = callback_url

        if return_url:
            payload["return_url"] = return_url

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

def generate_deposit_payment(user_data, amount):
    """Generate a payment link for deposits"""
    try:
        # Generate a unique transaction reference
        tx_ref = generate_tx_ref("DEP")

        # Prepare user data
        email = f"{user_data['telegram_id']}@alipayeth.com"

        # Get name parts
        name_parts = user_data['name'].split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else "User"

        # Create the payment
        response = create_payment(
            amount=amount,
            currency="ETB",
            email=email,
            first_name=first_name,
            last_name=last_name,
            tx_ref=tx_ref,
            callback_url=f"https://alipay-eth-bot.replit.app/chapa/webhook"
        )

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
        # Generate a unique transaction reference
        tx_ref = generate_tx_ref("REG")

        # Prepare user data
        email = f"{user_data['telegram_id']}@alipayeth.com"

        # Get name parts
        name_parts = user_data['name'].split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else "User"

        # Create the payment
        response = create_payment(
            amount=1.0,  # Registration fee is $1
            currency="ETB",
            email=email,
            first_name=first_name,
            last_name=last_name,
            tx_ref=tx_ref,
            callback_url=f"https://alipay-eth-bot.replit.app/chapa/webhook"
        )

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
        url = f"https://api.chapa.co/v1/transaction/verify/{tx_ref}"
        headers = {
            "Authorization": f"Bearer {os.environ.get('CHAPA_SECRET_KEY')}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers)
        response_data = response.json()
        logger.info(f"Verify payment response: {response_data}")

        if response_data.get('status') == 'success' and response_data.get('data', {}).get('status') == 'success':
            return True

        return False
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        return False

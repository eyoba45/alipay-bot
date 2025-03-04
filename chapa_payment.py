#!/usr/bin/env python3
"""
Chapa Payment Gateway Integration
"""

import os
import logging
import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

def create_payment(amount, currency, callback_url):
    """Create a new payment with Chapa"""
    try:
        url = "https://api.chapa.co/payment"
        headers = {
            "Authorization": f"Bearer {os.environ.get('CHAPA_SECRET_KEY')}",
            "Content-Type": "application/json"
        }
        payload = {
            "amount": amount,
            "currency": currency,
            "callback_url": callback_url
        }
        response = requests.post(url, json=payload, headers=headers)
        response_data = response.json()
        logger.info(f"Create payment response: {response_data}")
        return response_data
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        return None


def generate_deposit_payment(user_data, amount):
    """Generate a deposit payment link for the user."""
    try:
        currency = user_data.get('currency', 'USD')  # Default to USD
        callback_url = user_data.get('callback_url', 'https://your.callback.url')  # Set your callback URL
        payment_response = create_payment(amount, currency, callback_url)
        if payment_response and 'checkout_url' in payment_response:
            return payment_response  # Return the payment link
        logger.error("Failed to generate deposit payment.")
        return None
    except Exception as e:
        logger.error(f"Error generating deposit payment: {e}")
        return None
   

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
        # Mock implementation of payment creation
        response = requests.post(
            "https://api.chapa.co/pay",
            json={"amount": amount, "currency": currency, "callback_url": callback_url}
        )
        logger.info(f"Create payment response: {response.json()}")
        return response.json()  # Modify according to your actual API behavior
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
   

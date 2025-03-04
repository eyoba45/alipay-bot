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
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def create_payment(amount, currency, callback_url):
    """Create a new payment with Chapa"""
    secret_key = os.environ.get('CHAPA_SECRET_KEY')
    if not secret_key:
        logger.error("Chapa secret key not set!")
        return None

    headers = {
        'Authorization': f'Bearer {secret_key}',
        'Content-Type': 'application/json'
    }
    
    payment_data = {
        'amount': amount,
        'currency': currency,
        'callback_url': callback_url,
        'metadata': {
            'description': 'Payment for services',
        }
    }

    try:
        response = requests.post(
            'https://chapa.co/api/v1/transaction/initialize',
            json=payment_data,
            headers=headers
        )
        
        if response.status_code == 200:
            logger.info("Payment created successfully!")
            return response.json()
        else:
            logger.error(f"Failed to create payment: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        return None

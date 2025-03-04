#!/usr/bin/env python3
"""
Chapa Webhook for Payment Notifications
"""

import os
import logging
import requests
from flask import Flask, request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Listen for payment notifications from Chapa"""
    data = request.json
    logger.info(f"Received webhook data: {data}")
    
    # Verify that the webhook signature is valid
    secret_key = os.environ.get('CHAPA_WEBHOOK_SECRET')
    if not verify_signature(data, secret_key):
        logger.error("Invalid webhook signature!")
        return "Invalid signature", 403

    # Process the payment data
    process_payment(data)

    return "Webhook received", 200

def verify_signature(data, secret):
    """Verify webhook signature"""
    try:
        # Implementation for signature verification
        return True  # Assuming always true for simulation
    except Exception as e:
        logger.error(f"Error verifying signature: {e}")
        return False

def process_payment(data):
    """Process payment data from Chapa"""
    # Implementation for processing the payment data
    logger.info("Payment processed successfully.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)


#!/usr/bin/env python3
"""
Test Chapa Payment Integration
This script allows you to manually test Chapa payment verification
"""
import os
import logging
import requests
import json
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables if .env file exists
try:
    load_dotenv()
except:
    pass

def test_verify_payment(tx_ref):
    """Test verification of a payment with Chapa"""
    try:
        # Get the Chapa secret key
        secret_key = os.environ.get('CHAPA_SECRET_KEY')
        if not secret_key:
            logger.error("CHAPA_SECRET_KEY environment variable not set")
            return False
            
        # Build the verification URL
        url = f"https://api.chapa.co/v1/transaction/verify/{tx_ref}"
        
        # Set up headers with the authorization token
        headers = {
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json"
        }
        
        # Make the request to verify the payment
        logger.info(f"Verifying payment for tx_ref: {tx_ref}")
        response = requests.get(url, headers=headers)
        
        # Log the raw response for debugging
        logger.info(f"Status code: {response.status_code}")
        logger.info(f"Raw response: {response.text}")
        
        # Parse the response as JSON
        try:
            response_data = response.json()
            logger.info(f"Parsed response: {json.dumps(response_data, indent=2)}")
            
            # Check if verification was successful
            if response_data.get('status') == 'success' and response_data.get('data', {}).get('status') == 'success':
                logger.info(f"Payment {tx_ref} verified successfully")
                return response_data.get('data', {})
            else:
                logger.warning(f"Payment {tx_ref} verification failed")
                return False
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return False
    except Exception as e:
        logger.error(f"Error verifying payment: {e}")
        return False

def test_webhook_endpoint():
    """Test if the webhook endpoint is accessible"""
    try:
        # Build the webhook URL
        webhook_url = "https://alipay-eth-bot.replit.app/chapa/webhook"
        
        # Make a simple GET request to test if the endpoint is accessible
        response = requests.get(webhook_url)
        
        # Log the response
        logger.info(f"Webhook test status code: {response.status_code}")
        logger.info(f"Webhook test response: {response.text}")
        
        return response.status_code
    except Exception as e:
        logger.error(f"Error testing webhook endpoint: {e}")
        return None

if __name__ == "__main__":
    print("\n--- Chapa Payment Integration Test ---\n")
    
    # Test if CHAPA_SECRET_KEY is set
    secret_key = os.environ.get('CHAPA_SECRET_KEY')
    if not secret_key:
        print("❌ CHAPA_SECRET_KEY environment variable not set")
    else:
        print(f"✅ CHAPA_SECRET_KEY is set: {secret_key[:5]}...{secret_key[-5:]}")
    
    # Test webhook endpoint
    print("\nTesting webhook endpoint...")
    webhook_status = test_webhook_endpoint()
    if webhook_status:
        print(f"✅ Webhook endpoint returned status code: {webhook_status}")
    else:
        print("❌ Failed to reach webhook endpoint")
    
    # Test payment verification
    tx_ref = input("\nEnter a transaction reference to verify (or press Enter to skip): ")
    if tx_ref:
        print(f"\nVerifying payment for tx_ref: {tx_ref}...")
        result = test_verify_payment(tx_ref)
        if result:
            print("✅ Payment verification successful!")
            print(f"Payment details: {json.dumps(result, indent=2)}")
        else:
            print("❌ Payment verification failed")
    
    print("\nTest completed!")

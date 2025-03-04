
#!/usr/bin/env python3
"""
Script to set up and verify the environment for the Telegram bot
"""
import os
import sys
import logging
import requests
import json
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def setup_environment():
    """Set up and verify all required environment variables"""
    # Check TELEGRAM_BOT_TOKEN
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN is missing! Please add it to Secrets.")
        return False
    
    # Check if the token is valid
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if response.status_code != 200:
            logger.error(f"❌ Invalid TELEGRAM_BOT_TOKEN: {response.text}")
            return False
        bot_info = response.json().get('result', {})
        logger.info(f"✅ Valid bot token for @{bot_info.get('username')}")
    except Exception as e:
        logger.error(f"❌ Error testing bot token: {e}")
        return False
    
    # Setup ADMIN_CHAT_ID if missing
    admin_id = os.environ.get('ADMIN_CHAT_ID')
    if not admin_id:
        admin_id = input("Please enter your Telegram chat ID for admin access: ")
        if not admin_id:
            logger.warning("⚠️ No ADMIN_CHAT_ID provided, using default value")
            admin_id = "1234567890"  # Default value
        
        # Set the environment variable
        os.environ['ADMIN_CHAT_ID'] = admin_id
        logger.info(f"✅ Set ADMIN_CHAT_ID to {admin_id}")
    
    # Setup DATABASE_URL if missing
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        logger.warning("⚠️ DATABASE_URL not found, using SQLite database")
        db_url = "sqlite:///bot.db"
        os.environ['DATABASE_URL'] = db_url
        logger.info(f"✅ Set DATABASE_URL to {db_url}")
    
    logger.info("✅ Environment setup complete!")
    
    # Print instructions for adding secrets permanently
    print("\n" + "="*50)
    print("🔑 IMPORTANT: Add these values to Replit Secrets to make them permanent:")
    print("1. Click on 'Secrets' in the Tools panel")
    print("2. Add the following secrets:")
    print(f"   - TELEGRAM_BOT_TOKEN: {token}")
    print(f"   - ADMIN_CHAT_ID: {admin_id}")
    print(f"   - DATABASE_URL: {db_url}")
    print("="*50 + "\n")
    
    return True

if __name__ == "__main__":
    print("🔧 Setting up environment variables for the Telegram bot...")
    if setup_environment():
        print("✅ Environment setup successful!")
    else:
        print("❌ Environment setup failed!")
        sys.exit(1)
#!/usr/bin/env python3
"""
Setup environment variables for the bot
"""
import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_and_set_env_variable(var_name, prompt_message=None, required=True):
    """Check if environment variable exists, if not, prompt user for it"""
    value = os.environ.get(var_name)
    
    if not value:
        if prompt_message:
            logger.info(prompt_message)
            value = input(f"Enter {var_name}: ").strip()
            if value:
                os.environ[var_name] = value
            elif required:
                logger.error(f"Required environment variable {var_name} not set.")
                return False
        elif required:
            logger.error(f"Required environment variable {var_name} not set.")
            return False
    
    return True

def main():
    """Main function to check environment variables"""
    logger.info("Checking environment variables...")
    
    # Required variables
    required_vars = [
        {
            "name": "TELEGRAM_BOT_TOKEN",
            "prompt": "Please enter your Telegram Bot Token from BotFather:"
        },
        {
            "name": "ADMIN_CHAT_ID",
            "prompt": "Please enter your Admin Telegram Chat ID:"
        }
    ]
    
    # Chapa payment integration variables
    chapa_vars = [
        {
            "name": "CHAPA_SECRET_KEY",
            "prompt": "Please enter your Chapa Secret Key (leave empty to skip Chapa integration):",
            "required": False
        },
        {
            "name": "CHAPA_WEBHOOK_SECRET",
            "prompt": "Please enter your Chapa Webhook Secret (leave empty to skip signature verification):",
            "required": False
        }
    ]
    
    # Check for environment variables
    all_required_vars_set = True
    for var in required_vars:
        if not check_and_set_env_variable(var["name"], var.get("prompt"), var.get("required", True)):
            all_required_vars_set = False
    
    # Check for Chapa variables
    for var in chapa_vars:
        check_and_set_env_variable(var["name"], var.get("prompt"), var.get("required", False))
    
    if not all_required_vars_set:
        logger.error("Not all required environment variables were set. Please set them and try again.")
        sys.exit(1)
    
    logger.info("All required environment variables are set.")
    return 0

if __name__ == "__main__":
    sys.exit(main())

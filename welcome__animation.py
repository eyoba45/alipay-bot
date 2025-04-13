#!/usr/bin/env python3
"""
Welcome Animation for AliPay_ETH Telegram Bot
This module provides animated welcome messages for Telegram bot users
"""
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def send_personalized_welcome(bot, chat_id, user_data=None):
    """Send a personalized welcome message
    
    Args:
        bot: Telegram bot instance
        chat_id: User's chat ID
        user_data: Dictionary containing user data (name, etc.)
    
    Returns:
        The message object or None if error
    """
    try:
        # Get user's name if available
        name = "there"
        if user_data and 'name' in user_data and user_data['name']:
            name = user_data['name']
        
        # First send a typing indicator to create anticipation
        bot.send_chat_action(chat_id, 'typing')
        
        # Send loading message
        bot.send_message(
            chat_id, 
            "🔄 Preparing your personalized experience...",
            parse_mode='HTML'
        )
        
        # Send another typing indicator
        bot.send_chat_action(chat_id, 'typing')
        
        # Create a more decorative welcome message
        welcome_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✨ <b>WELCOME, {name.upper()}!</b> ✨  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

🌟 <b>AliPay_ETH at Your Service!</b> 🌟

🛍️ Your Ethiopian gateway to AliExpress
💳 Easy payments in Ethiopian Birr
🚚 Reliable order tracking & delivery
💯 Trusted by thousands of customers

<i>We're excited to have you join our community!</i>
        """
        
        # Send welcome message
        message = bot.send_message(
            chat_id,
            welcome_message,
            parse_mode='HTML'
        )
        
        logger.info(f"Sent personalized welcome message to user {chat_id}")
        return message
        
    except Exception as e:
        logger.error(f"Error in personalized welcome: {e}")
        # Return None on error
        return None

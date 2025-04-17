#!/usr/bin/env python3
"""
Welcome Animation for AliPay_ETH Telegram Bot
This module provides animated welcome messages for Telegram bot users with bot personality introduction
"""
import logging
import time
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot personality traits and introduction elements
BOT_PERSONALITY = {
    "name": "AliPay_ETH",
    "traits": [
        "Friendly and approachable",
        "Efficient and reliable",
        "Ethiopian e-commerce expert",
        "Multilingual shopping assistant",
        "Secured payment processor"
    ],
    "slogans": [
        "Your Ethiopian gateway to global shopping!",
        "Shop smart, pay local with AliPay_ETH!",
        "Where Ethiopian Birr meets AliExpress!",
        "Making global shopping local since 2023!",
        "Your trusted AliExpress payment partner in Ethiopia!"
    ],
    "greetings": [
        "I'm excited to help you shop globally with local convenience!",
        "Ready to transform your shopping experience!",
        "Can't wait to show you how easy international shopping can be!",
        "Looking forward to being your shopping assistant!",
        "Thrilled to guide you through your AliExpress journey!"
    ]
}

def send_personalized_welcome(bot, chat_id, user_data=None):
    """Send a personalized welcome message with animated bot introduction
    
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
        
        # ANIMATION SEQUENCE - STAGE 1: Initial Connection
        
        # First send a typing indicator to create anticipation
        bot.send_chat_action(chat_id, 'typing')
        time.sleep(1)  # Pause for effect
        
        # First animation frame - connection established
        loading_msg = bot.send_message(
            chat_id, 
            "🔄 <b>Establishing secure connection...</b>",
            parse_mode='HTML'
        )
        time.sleep(1.2)  # Pause for effect
        
        # ANIMATION SEQUENCE - STAGE 2: System Boot
        
        # Second animation frame - system initialization
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text="⚙️ <b>Initializing AliPay_ETH systems...</b>",
            parse_mode='HTML'
        )
        time.sleep(1.5)  # Slightly longer pause for effect
        
        # Third animation frame - user detection
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text="🔍 <b>Detecting user profile...</b>",
            parse_mode='HTML'
        )
        
        # Show typing indicator again
        bot.send_chat_action(chat_id, 'typing')
        time.sleep(1.3)  # Slightly different pause for natural feel
        
        # ANIMATION SEQUENCE - STAGE 3: Personality Activation
        
        # Fourth animation frame - user found
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text=f"✅ <b>User identified: {name}</b>\n🔄 Activating personality matrix...",
            parse_mode='HTML'
        )
        time.sleep(1.4)
        
        # Fifth animation frame - personality engaged
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text="🤖 <b>AI Assistant personality engaged!</b>\n🚀 Launching personalized interface...",
            parse_mode='HTML'
        )
        time.sleep(1)
        
        # MAIN WELCOME MESSAGE WITH PERSONALITY INTRODUCTION
        
        # Select random elements for personality variation
        slogan = random.choice(BOT_PERSONALITY["slogans"])
        greeting = random.choice(BOT_PERSONALITY["greetings"])
        traits = random.sample(BOT_PERSONALITY["traits"], 3)  # Pick 3 random traits
        
        # Create an eye-catching welcome message with bot personality
        welcome_message = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮
    ✨✨✨ <b>WELCOME TO ALIPAY_ETH</b> ✨✨✨
╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯

🌟 <b>Hello, {name.upper()}!</b> 🌟

I'm your AliPay_ETH assistant, and I'm here to make your 
AliExpress shopping experience seamless and enjoyable!

<b>{slogan}</b>

┏━━━━━━ <b>WHO I AM</b> ━━━━━━┓
┃                              ┃
┃  ✓ {traits[0]}  ┃
┃  ✓ {traits[1]}  ┃
┃  ✓ {traits[2]}  ┃
┃                              ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

<i>{greeting}</i>

<b>Let's get started with an amazing shopping experience!</b>
        """
        
        # Delete the animation message
        bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)
        
        # Send final welcome message
        message = bot.send_message(
            chat_id,
            welcome_message,
            parse_mode='HTML'
        )
        
        logger.info(f"Sent personalized welcome with bot personality introduction to user {chat_id}")
        return message
        
    except Exception as e:
        logger.error(f"Error in personalized welcome animation: {e}")
        # Return simple message on error - use a default name in case the name variable is unbound
        fallback_name = "there"
        if 'name' in locals():
            fallback_name = name
            
        return bot.send_message(
            chat_id,
            f"<b>Hello, {fallback_name}!</b>\n\n✨ Welcome to AliPay_ETH! ✨\n\nYour Ethiopian gateway to AliExpress shopping.",
            parse_mode='HTML'
        )

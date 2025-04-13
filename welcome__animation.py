#!/usr/bin/env python3
"""
Welcome Animation for AliPay_ETH Telegram Bot
This module provides animated welcome messages for Telegram bot users
"""
import time
import logging
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Animation frames for welcome message
WELCOME_FRAMES = [
    "🔄 Loading your personalized experience",
    "🔄 Loading your personalized experience.",
    "🔄 Loading your personalized experience..",
    "🔄 Loading your personalized experience...",
    "✨ Welcome to AliPay_ETH! ✨"
]

# Different emoji sets for animation variety
EMOJI_SETS = [
    ["🛍️", "📦", "🚚", "📬", "🎁"],  # Shopping animation
    ["💰", "💸", "💳", "🏦", "💵"],   # Payment animation
    ["🌱", "🌿", "🌲", "🌳", "🌴"],   # Growth animation
    ["🕐", "🕑", "🕒", "🕓", "🕔"],   # Clock animation
    ["🌍", "🌎", "🌏", "🌐", "🌍"]    # World animation
]

def send_personalized_welcome(bot, chat_id, user_data=None):
    """Send a personalized welcome message with animated effect
    
    Args:
        bot: Telegram bot instance
        chat_id: User's chat ID
        user_data: Dictionary containing user data (name, etc.)
    
    Returns:
        The final message object or None if error
    """
    try:
        # Extract user info
        name = user_data.get('name', 'there') if user_data else 'there'
        
        # Create personalized greeting
        greeting = f"<b>Hello, {name}!</b>\n\n"
        
        # Choose a random emoji set
        emoji_set = random.choice(EMOJI_SETS)
        
        # Send initial welcome message
        message = bot.send_message(
            chat_id,
            greeting + WELCOME_FRAMES[0],
            parse_mode='HTML'
        )
        
        # Animate the welcome message
        for i in range(1, 4):
            time.sleep(0.7)  # Delay between animation frames
            try:
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    text=greeting + WELCOME_FRAMES[i] + " " + emoji_set[i],
                    parse_mode='HTML'
                )
            except Exception as edit_error:
                logger.warning(f"Edit message error in animation: {edit_error}")
                # Continue with animation even if one frame fails
                continue
        
        # Send final welcome frame
        time.sleep(0.7)
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.message_id,
                text=greeting + WELCOME_FRAMES[4],
                parse_mode='HTML'
            )
        except Exception as final_error:
            logger.warning(f"Error showing final animation frame: {final_error}")
        
        return message
    except Exception as e:
        logger.error(f"Error in personalized welcome: {e}")
        # Fallback to simple welcome if animation fails
        try:
            return bot.send_message(
                chat_id,
                f"<b>Hello, {name}!</b>\n\n✨ Welcome to AliPay_ETH! ✨",
                parse_mode='HTML'
            )
        except Exception:
            logger.error("Failed to send even fallback welcome message")
            return None

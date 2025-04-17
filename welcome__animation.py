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
    """Send a personalized welcome message with enhanced animated bot introduction
    
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
        time.sleep(0.8)
        
        # =============== STAGE 1: SYSTEM BOOT SEQUENCE ===============
        # Create an animated loading sequence with progress indicators
        loading_frames = ["⬛⬛⬛⬛⬛⬛⬛⬛⬛⬛ 0%", "🟩⬛⬛⬛⬛⬛⬛⬛⬛⬛ 10%", 
                         "🟩🟩⬛⬛⬛⬛⬛⬛⬛⬛ 20%", "🟩🟩🟩⬛⬛⬛⬛⬛⬛⬛ 30%", 
                         "🟩🟩🟩🟩⬛⬛⬛⬛⬛⬛ 40%", "🟩🟩🟩🟩🟩⬛⬛⬛⬛⬛ 50%",
                         "🟩🟩🟩🟩🟩🟩⬛⬛⬛⬛ 60%", "🟩🟩🟩🟩🟩🟩🟩⬛⬛⬛ 70%",
                         "🟩🟩🟩🟩🟩🟩🟩🟩⬛⬛ 80%", "🟩🟩🟩🟩🟩🟩🟩🟩🟩⬛ 90%",
                         "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100%"]
        
        # Initial message with system boot animation
        loading_msg = bot.send_message(
            chat_id, 
            f"🔄 <b>SYSTEM BOOT SEQUENCE INITIATED</b>\n\n"
            f"🔐 Establishing secure connection...\n"
            f"{loading_frames[0]}",
            parse_mode='HTML'
        )
        
        # Animated loading bar
        for i in range(1, len(loading_frames)):
            time.sleep(0.4)  # Quick animation for the loading bar
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_msg.message_id,
                text=f"🔄 <b>SYSTEM BOOT SEQUENCE INITIATED</b>\n\n"
                    f"🔐 Establishing secure connection...\n"
                    f"{loading_frames[i]}",
                parse_mode='HTML'
            )
        
        # =============== STAGE 2: SYSTEM INITIALIZATION ===============
        time.sleep(0.5)
        
        # System initialization animation with spinning effect
        init_frames = ["⚙️ <b>Initializing AliPay_ETH systems</b> ⏳", 
                       "⚙️ <b>Initializing AliPay_ETH systems.</b> ⏳",
                       "⚙️ <b>Initializing AliPay_ETH systems..</b> ⏳", 
                       "⚙️ <b>Initializing AliPay_ETH systems...</b> ⏳"]
        
        for frame in init_frames * 2:  # Repeat the animation twice
            time.sleep(0.3)
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_msg.message_id,
                text=f"{frame}\n\n"
                    f"✅ Secure connection established\n"
                    f"⏳ Loading core modules...\n"
                    f"{loading_frames[-1]}",
                parse_mode='HTML'
            )
        
        # =============== STAGE 3: USER DETECTION & VERIFICATION ===============
        # Show typing indicator again for natural conversation flow
        bot.send_chat_action(chat_id, 'typing')
        time.sleep(0.8)
        
        # User detection animation
        scan_frames = ["🔍 <b>Scanning for user profile</b> |", 
                      "🔍 <b>Scanning for user profile</b> /", 
                      "🔍 <b>Scanning for user profile</b> —", 
                      "🔍 <b>Scanning for user profile</b> \\"]
        
        for frame in scan_frames * 2:  # Repeat the animation twice
            time.sleep(0.3)
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_msg.message_id,
                text=f"{frame}\n\n"
                    f"✅ Secure connection established\n"
                    f"✅ Core modules loaded\n"
                    f"⏳ Identifying user...",
                parse_mode='HTML'
            )
        
        # User identified with custom data
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text=f"✅ <b>USER PROFILE DETECTED</b>\n\n"
                f"👤 <b>User:</b> {name}\n"
                f"🆔 <b>ID:</b> {chat_id}\n"
                f"🌐 <b>Platform:</b> Telegram\n"
                f"🔄 Activating assistant protocols...",
            parse_mode='HTML'
        )
        time.sleep(1.2)
        
        # =============== STAGE 4: PERSONALITY MATRIX ACTIVATION ===============
        # Visual startup sequence for the AI assistant personality
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=loading_msg.message_id,
            text=f"🤖 <b>AI ASSISTANT INITIALIZATION</b>\n\n"
                f"<pre>Loading personality matrix...</pre>\n"
                f"<pre>Calibrating response patterns...</pre>\n"
                f"<pre>Syncing language modules...</pre>\n"
                f"<pre>Optimizing user experience...</pre>",
            parse_mode='HTML'
        )
        time.sleep(1.2)
        
        # Final activation with flashing effect
        activation_frames = [
            "🚀 <b>LAUNCHING ALIPAY_ETH INTERFACE</b> 🚀",
            "🌟 <b>LAUNCHING ALIPAY_ETH INTERFACE</b> 🌟",
            "💫 <b>LAUNCHING ALIPAY_ETH INTERFACE</b> 💫",
            "✨ <b>LAUNCHING ALIPAY_ETH INTERFACE</b> ✨"
        ]
        
        for frame in activation_frames:
            time.sleep(0.3)
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_msg.message_id,
                text=f"{frame}\n\n"
                    f"<pre>Personality: ACTIVE</pre>\n"
                    f"<pre>Systems: ONLINE</pre>\n"
                    f"<pre>Status: READY</pre>\n"
                    f"<pre>User Experience: OPTIMIZED</pre>",
                parse_mode='HTML'
            )
        
        # =============== MAIN WELCOME MESSAGE WITH RICH FORMATTING ===============
        # Select random elements for personality variation
        slogan = random.choice(BOT_PERSONALITY["slogans"])
        greeting = random.choice(BOT_PERSONALITY["greetings"])
        traits = random.sample(BOT_PERSONALITY["traits"], 3)  # Pick 3 random traits
        
        # Enhanced border pattern
        border_top = "╭" + "━" * 48 + "╮"
        border_bottom = "╰" + "━" * 48 + "╯"
        
        # Create a visually stunning welcome message with emoji decorations
        welcome_message = f"""
{border_top}
    ✨✨✨ <b>WELCOME TO ALIPAY_ETH</b> ✨✨✨
{border_bottom}

🌟 <b>Hello, {name.upper()}!</b> 🌟

I'm your <b>AliPay_ETH assistant</b>, and I'm here to make your 
AliExpress shopping experience seamless and enjoyable!

📣 <b>{slogan}</b> 📣

┏━━━━━━━━━ <b>WHO I AM</b> ━━━━━━━━━┓
┃                                   ┃
┃  ✅ {traits[0]}  ┃
┃  ✅ {traits[1]}  ┃
┃  ✅ {traits[2]}  ┃
┃                                   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

<i>"{greeting}"</i>

🚀 <b>Let's get started with an amazing shopping experience!</b> 🚀

💡 <b>TIP:</b> Use the menu buttons below to navigate through all services
        """
        
        # Delete the animation message
        bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)
        
        # Send the final welcome message with keyboard
        message = bot.send_message(
            chat_id,
            welcome_message,
            parse_mode='HTML'
        )
        
        logger.info(f"Sent enhanced animated welcome with bot personality introduction to user {chat_id}")
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

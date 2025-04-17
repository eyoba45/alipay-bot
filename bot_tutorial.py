#!/usr/bin/env python3
"""
Interactive Telegram Bot Tutorial and Onboarding Module
Provides step-by-step walkthrough for new users to learn bot features
"""
import os
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telebot.types import KeyboardButton, Message, CallbackQuery
from datetime import datetime, timedelta
import time
import traceback
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Tutorial states tracking
user_tutorial_state = {}
TUTORIAL_TIMEOUT = 3600  # 1 hour timeout for tutorial sessions

# Tutorial steps definition
TUTORIAL_STEPS = {
    'start': {
        'title': '👋 Welcome to AliPay ETH Bot Tutorial!',
        'content': (
            "This interactive tutorial will guide you through all the features of our service. "
            "Let's learn how to use this bot step by step!\n\n"
            "The tutorial should take about 5 minutes to complete."
        ),
        'next_step': 'registration',
        'buttons': [
            {'text': '▶️ Start Tutorial', 'callback': 'tutorial_next'},
            {'text': '❌ Skip Tutorial', 'callback': 'tutorial_skip'}
        ]
    },
    'registration': {
        'title': '📝 Step 1: Registration',
        'content': (
            "To use our service, you need to register first!\n\n"
            "Registration requires:\n"
            "• Your Name\n"
            "• Address\n"
            "• Phone Number\n"
            "• One-time registration fee of 200 birr\n"
            "• First month subscription fee of 150 birr\n\n"
            "Your total registration payment will be 350 birr."
        ),
        'next_step': 'payment',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'payment': {
        'title': '💳 Step 2: Payment Methods',
        'content': (
            "We offer secure payment through Chapa, supporting:\n\n"
            "• TeleBirr\n"
            "• Bank Transfer\n"
            "• Card Payment\n\n"
            "Once your payment is confirmed, your account is automatically activated!"
        ),
        'next_step': 'deposit',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'deposit': {
        'title': '💰 Step 3: Deposit Funds',
        'content': (
            "After registration, you can deposit funds to your account.\n\n"
            "Available deposit amounts:\n"
            "• $5 (800 birr)\n"
            "• $10 (1,600 birr)\n"
            "• $15 (2,400 birr)\n"
            "• $20 (3,200 birr)\n"
            "• Custom amount\n\n"
            "Exchange rate: 1 USD = 160 ETB"
        ),
        'next_step': 'order',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'order': {
        'title': '🛍️ Step 4: Submit an Order',
        'content': (
            "Ready to shop on AliExpress? Here's how to place an order:\n\n"
            "1. Find products on AliExpress\n"
            "2. Copy the product link\n"
            "3. Click 'Submit Order' button\n"
            "4. Paste the link when prompted\n"
            "5. Confirm your order\n\n"
            "Our team will process your order and keep you updated!"
        ),
        'next_step': 'tracking',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'tracking': {
        'title': '📦 Step 5: Order Tracking',
        'content': (
            "Track your orders easily:\n\n"
            "1. Click 'Track Order' button\n"
            "2. Enter your order number\n"
            "3. View detailed order status\n\n"
            "You'll receive notifications when your order status changes!"
        ),
        'next_step': 'subscription',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'subscription': {
        'title': '📅 Step 6: Subscription Management',
        'content': (
            "Your subscription costs 150 birr per month.\n\n"
            "• Check your subscription status anytime\n"
            "• Receive reminders before expiration\n"
            "• Subscription fee can be added to your deposit\n"
            "• Maintain active subscription to use services"
        ),
        'next_step': 'referral',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'referral': {
        'title': '👥 Step 7: Referral Program',
        'content': (
            "Earn rewards by inviting friends!\n\n"
            "• Receive 50 points (50 birr) for each successful referral\n"
            "• Share your unique referral link\n"
            "• Earn badges as you refer more people\n"
            "• Redeem points for account balance\n\n"
            "Referral Badges:\n"
            "🥉 Bronze: 3 referrals\n"
            "🥈 Silver: 5 referrals\n"
            "🥇 Gold: 10 referrals\n"
            "💎 Diamond: 20 referrals\n"
            "🏆 Legendary: 50 referrals"
        ),
        'next_step': 'assistant',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'assistant': {
        'title': '🤖 Step 8: AI Assistant',
        'content': (
            "Our AI Assistant is here to help!\n\n"
            "• Powered by advanced Llama 3 70B model\n"
            "• Get help with any bot feature\n"
            "• Ask questions about AliExpress shopping\n"
            "• Available 24/7 through the 'AI Assistant' button\n\n"
            "Try it out to get personalized assistance!"
        ),
        'next_step': 'complete',
        'buttons': [
            {'text': '▶️ Continue', 'callback': 'tutorial_next'},
            {'text': '◀️ Back', 'callback': 'tutorial_prev'},
            {'text': '❌ Exit Tutorial', 'callback': 'tutorial_exit'}
        ]
    },
    'complete': {
        'title': '🎉 Tutorial Complete!',
        'content': (
            "Congratulations! You've completed the AliPay ETH Bot tutorial.\n\n"
            "You now know how to:\n"
            "✅ Register and make payments\n"
            "✅ Deposit funds to your account\n"
            "✅ Submit and track orders\n"
            "✅ Manage your subscription\n"
            "✅ Use the referral program\n"
            "✅ Get help from the AI Assistant\n\n"
            "Need help anytime? Use the Help Center button or ask our AI Assistant!"
        ),
        'next_step': None,
        'buttons': [
            {'text': '🏠 Return to Main Menu', 'callback': 'tutorial_exit'},
            {'text': '📝 Register Now', 'callback': 'tutorial_register'},
            {'text': '❓ Help Center', 'callback': 'tutorial_help'}
        ]
    }
}

def get_tutorial_keyboard(step):
    """Create inline keyboard for tutorial navigation"""
    keyboard = InlineKeyboardMarkup()
    row = []
    
    for button in TUTORIAL_STEPS[step]['buttons']:
        row.append(InlineKeyboardButton(
            text=button['text'],
            callback_data=button['callback']
        ))
        
        # Create a new row after every 2 buttons
        if len(row) == 2:
            keyboard.row(*row)
            row = []
    
    # Add any remaining buttons
    if row:
        keyboard.row(*row)
        
    return keyboard

def start_tutorial(bot, message, from_help=False):
    """Start the interactive tutorial sequence"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Reset tutorial state for this user
    user_tutorial_state[user_id] = {
        'current_step': 'start',
        'start_time': datetime.now(),
        'from_help': from_help
    }
    
    step_info = TUTORIAL_STEPS['start']
    
    # Send initial tutorial message
    bot.send_message(
        chat_id,
        f"<b>{step_info['title']}</b>\n\n{step_info['content']}",
        parse_mode='HTML',
        reply_markup=get_tutorial_keyboard('start')
    )
    
    # Set up timeout cleanup
    threading.Timer(TUTORIAL_TIMEOUT, lambda: cleanup_tutorial(user_id)).start()
    
    logger.info(f"Started tutorial for user {user_id}")

def cleanup_tutorial(user_id):
    """Clean up expired tutorial sessions"""
    if user_id in user_tutorial_state:
        if (datetime.now() - user_tutorial_state[user_id]['start_time']).total_seconds() > TUTORIAL_TIMEOUT:
            del user_tutorial_state[user_id]
            logger.info(f"Cleaned up expired tutorial session for user {user_id}")

def handle_tutorial_callback(bot, call):
    """Handle callback queries from tutorial buttons"""
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    callback_data = call.data
    
    # Check if user is in tutorial mode
    if user_id not in user_tutorial_state:
        bot.answer_callback_query(call.id, "Tutorial session expired. Please start again.")
        return
    
    current_step = user_tutorial_state[user_id]['current_step']
    step_info = TUTORIAL_STEPS[current_step]
    
    if callback_data == 'tutorial_next':
        # Move to next step
        next_step = step_info['next_step']
        if next_step:
            user_tutorial_state[user_id]['current_step'] = next_step
            next_step_info = TUTORIAL_STEPS[next_step]
            
            # Edit message with new step content
            bot.edit_message_text(
                f"<b>{next_step_info['title']}</b>\n\n{next_step_info['content']}",
                chat_id=chat_id,
                message_id=call.message.message_id,
                parse_mode='HTML',
                reply_markup=get_tutorial_keyboard(next_step)
            )
            bot.answer_callback_query(call.id)
        
    elif callback_data == 'tutorial_prev':
        # Find previous step
        for step, info in TUTORIAL_STEPS.items():
            if info['next_step'] == current_step:
                user_tutorial_state[user_id]['current_step'] = step
                
                # Edit message with previous step content
                bot.edit_message_text(
                    f"<b>{info['title']}</b>\n\n{info['content']}",
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=get_tutorial_keyboard(step)
                )
                break
        bot.answer_callback_query(call.id)
    
    elif callback_data == 'tutorial_exit':
        # End tutorial
        from_help = user_tutorial_state[user_id].get('from_help', False)
        del user_tutorial_state[user_id]
        
        # Return to main menu
        bot.edit_message_text(
            "✅ <b>Tutorial closed.</b>\n\nYou can restart the tutorial anytime by typing /tutorial or via the Help Center.",
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode='HTML'
        )
        
        # Return to main menu or help center
        if from_help:
            try:
                from bot import help_center
                help_center(call.message)
            except Exception as e:
                logger.error(f"Error returning to help center: {e}")
                # Fallback to main menu
                try:
                    from bot import create_main_menu
                    bot.send_message(
                        chat_id,
                        "Returning to main menu...",
                        reply_markup=create_main_menu(chat_id=chat_id)
                    )
                except Exception as menu_error:
                    logger.error(f"Error creating main menu: {menu_error}")
        else:
            try:
                from bot import create_main_menu
                bot.send_message(
                    chat_id,
                    "Returning to main menu...",
                    reply_markup=create_main_menu(chat_id=chat_id)
                )
            except Exception as menu_error:
                logger.error(f"Error creating main menu: {menu_error}")
        
        bot.answer_callback_query(call.id)
    
    elif callback_data == 'tutorial_skip':
        # Skip tutorial
        del user_tutorial_state[user_id]
        
        bot.edit_message_text(
            "Tutorial skipped. You can start it again anytime by typing /tutorial.",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
        
        # Return to main menu
        try:
            from bot import create_main_menu
            bot.send_message(
                chat_id,
                "Returning to main menu...",
                reply_markup=create_main_menu(chat_id=chat_id)
            )
        except Exception as menu_error:
            logger.error(f"Error creating main menu: {menu_error}")
        
        bot.answer_callback_query(call.id)
    
    elif callback_data == 'tutorial_register':
        # Start registration process
        del user_tutorial_state[user_id]
        
        bot.edit_message_text(
            "Starting registration process...",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
        
        # Redirect to registration
        try:
            from bot import register_user
            register_user(call.message)
        except Exception as e:
            logger.error(f"Error starting registration: {e}")
            bot.send_message(
                chat_id,
                "Sorry, there was an error starting registration. Please use the 'Register' button from the main menu."
            )
        
        bot.answer_callback_query(call.id)
    
    elif callback_data == 'tutorial_help':
        # Go to help center
        del user_tutorial_state[user_id]
        
        bot.edit_message_text(
            "Opening Help Center...",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
        
        # Redirect to help center
        try:
            from bot import help_center
            help_center(call.message)
        except Exception as e:
            logger.error(f"Error opening help center: {e}")
            bot.send_message(
                chat_id,
                "Sorry, there was an error opening the Help Center. Please use the 'Help Center' button from the main menu."
            )
        
        bot.answer_callback_query(call.id)

def check_and_clear_old_sessions():
    """Check and clear expired tutorial sessions"""
    to_remove = []
    now = datetime.now()
    
    for user_id, state in user_tutorial_state.items():
        if (now - state['start_time']).total_seconds() > TUTORIAL_TIMEOUT:
            to_remove.append(user_id)
    
    for user_id in to_remove:
        del user_tutorial_state[user_id]
    
    if to_remove:
        logger.info(f"Cleared {len(to_remove)} expired tutorial sessions")

def run_cleanup_thread():
    """Run a background thread to clean up expired tutorial sessions"""
    while True:
        try:
            check_and_clear_old_sessions()
        except Exception as e:
            logger.error(f"Error in tutorial cleanup thread: {e}")
        
        time.sleep(1800)  # Check every 30 minutes

# Start cleanup thread
cleanup_thread = threading.Thread(target=run_cleanup_thread, daemon=True)
cleanup_thread.start()

def is_in_tutorial(user_id):
    """Check if user is currently in tutorial mode"""
    return user_id in user_tutorial_state

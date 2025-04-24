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

# User tutorial state
user_tutorial_state = {}

# Tutorial timeout in seconds (15 minutes)
TUTORIAL_TIMEOUT = 15 * 60

# Tutorial steps - add more steps as needed
TUTORIAL_STEPS = {
    'start': {
        'title': '🎓 WELCOME TO THE INTERACTIVE TUTORIAL',
        'content': '''Welcome to AliPay ETH! This tutorial will guide you through the main features of our service.

Press <b>Next</b> to continue or <b>Skip</b> to exit the tutorial at any time.

What would you like to learn about first?''',
        'next_step': 'register'
    },
    'register': {
        'title': '📝 REGISTRATION',
        'content': '''The first step is to register for our service.

<b>Registration Process:</b>
1. Click "Register" on the main menu
2. Provide your name, address, and phone number
3. Pay the one-time fee of 200 birr + first month subscription of 150 birr
4. Wait for admin approval (automatic with Chapa API)

Once registered, you'll have full access to all features of our service!''',
        'next_step': 'deposit'
    },
    'deposit': {
        'title': '💰 DEPOSITS',
        'content': '''You'll need to deposit funds to place orders on AliExpress.

<b>How to deposit:</b>
1. Click "Deposit Funds" on the main menu
2. Choose an amount (fixed options or custom amount)
3. Complete the payment using TeleBirr
4. Submit your payment screenshot
5. Receive confirmation once your payment is verified

All deposits are in birr (ETB). The conversion rate is 160 birr = 1 USD.''',
        'next_step': 'order'
    },
    'order': {
        'title': '🛍️ PLACING ORDERS',
        'content': '''Using our service to place AliExpress orders is easy:

<b>How to order:</b>
1. Find the item you want on AliExpress
2. Copy the product link
3. Click "Submit Order" on the main menu
4. Paste the link and verify details
5. Confirm your order
6. Receive your order tracking details

The cost will be deducted from your balance.''',
        'next_step': 'track'
    },
    'track': {
        'title': '🔍 TRACKING ORDERS',
        'content': '''Keep track of your orders at any time:

<b>To track your orders:</b>
1. Click "Track Order" on the main menu
2. Enter your order number or select from recent orders
3. View detailed status information
4. Receive updates when your order status changes

We provide regular updates as your order progresses.''',
        'next_step': 'subscription'
    },
    'subscription': {
        'title': '📅 MONTHLY SUBSCRIPTION',
        'content': '''Our service requires a monthly subscription of 150 birr.

<b>Subscription details:</b>
1. First month is included in registration fee
2. Renewal is 150 birr per month
3. Automatic renewal reminders sent before expiration
4. Easily renew by clicking "Check Subscription"

You'll receive notifications when your subscription is about to expire.''',
        'next_step': 'referral'
    },
    'referral': {
        'title': '👨‍👨‍👧‍👧 REFERRAL SYSTEM',
        'content': '''Earn rewards by inviting friends to our service!

<b>How the referral system works:</b>
1. Share your unique referral link with friends
2. When they register, you get 50 points
3. 1 point = 1 birr in credit
4. Redeem points for deposits
5. Earn special badges as you refer more people

Check your referrals and badges in the "Referral Badges" section.''',
        'next_step': 'ai_assistant'
    },
    'ai_assistant': {
        'title': '🤖 AI ASSISTANT',
        'content': '''Our bot includes an AI Assistant powered by Llama 3 70B!

<b>AI Assistant features:</b>
1. Answers questions about the bot and service
2. Provides shopping guidance for AliExpress
3. Helps troubleshoot common issues
4. Available 24/7 for instant support

Just click "AI Assistant" on the main menu to start chatting!''',
        'next_step': 'conclusion'
    },
    'conclusion': {
        'title': '✅ TUTORIAL COMPLETE!',
        'content': '''Congratulations! You've completed the tutorial and now know the basics of using our service.

<b>Remember:</b>
• Register to get started
• Deposit funds to place orders
• Submit AliExpress links to order
• Track your orders easily
• Check your subscription status
• Refer friends to earn rewards
• Use the AI Assistant for help

Ready to begin? Click below to register or return to the main menu.''',
        'next_step': None
    }
}

def get_tutorial_keyboard(step):
    """Create inline keyboard for tutorial navigation"""
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    # Navigation buttons
    nav_buttons = []
    
    # Check if there's a previous step by searching for steps that lead to current
    has_prev = False
    for s, info in TUTORIAL_STEPS.items():
        if info['next_step'] == step:
            has_prev = True
            break
    
    if has_prev:
        nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data="tutorial_prev"))
    
    # Check if there's a next step
    if TUTORIAL_STEPS[step]['next_step']:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data="tutorial_next"))
    
    # Add navigation row
    if nav_buttons:
        keyboard.row(*nav_buttons)
    
    # Special buttons for conclusion page
    if step == 'conclusion':
        keyboard.row(InlineKeyboardButton("📝 Register Now", callback_data="tutorial_register"))
    
    # Always add exit button
    keyboard.row(InlineKeyboardButton("❌ Exit Tutorial", callback_data="tutorial_exit"))
    
    # Add skip button at the start
    if step == 'start':
        keyboard.row(InlineKeyboardButton("⏭️ Skip Tutorial", callback_data="tutorial_skip"))
        keyboard.row(InlineKeyboardButton("❓ Help Center", callback_data="tutorial_help"))
    
    return keyboard

def start_tutorial(bot, message, from_help=False):
    """Start the interactive tutorial sequence"""
    try:
        # Get user ID and chat ID safely
        user_id = getattr(message.from_user, 'id', None)
        if not user_id:
            logger.error(f"Cannot start tutorial: user_id is not available in message object: {message}")
            # Try to extract chat_id directly from message if possible
            chat_id = getattr(message, 'chat', {}).get('id') or message.chat.id
            bot.send_message(
                chat_id,
                "❌ Sorry, there was an error starting the tutorial. Please try again later.",
                parse_mode='HTML'
            )
            return

        chat_id = message.chat.id
        logger.info(f"🎓 Starting interactive tutorial for user {user_id}, chat_id {chat_id}, from_help={from_help}")
        
        # Reset tutorial state for this user
        user_tutorial_state[user_id] = {
            'current_step': 'start',
            'start_time': datetime.now(),
            'from_help': from_help,
            'message_id': None  # Will store the message ID for editing
        }
        
        step_info = TUTORIAL_STEPS['start']
        
        # Log tutorial message being sent
        logger.info(f"📣 Sending tutorial step 'start' to user {user_id}")
        
        # Send initial tutorial message and store the resulting message object
        tutorial_message = bot.send_message(
            chat_id,
            f"<b>{step_info['title']}</b>\n\n{step_info['content']}",
            parse_mode='HTML',
            reply_markup=get_tutorial_keyboard('start')
        )
        
        # Store the message ID for later editing
        if tutorial_message and hasattr(tutorial_message, 'message_id'):
            user_tutorial_state[user_id]['message_id'] = tutorial_message.message_id
            logger.info(f"✅ Tutorial message sent successfully with ID: {tutorial_message.message_id}")
        else:
            logger.warning(f"⚠️ Could not get message ID from tutorial message for user {user_id}")
        
        # Set up timeout cleanup
        cleanup_timer = threading.Timer(TUTORIAL_TIMEOUT, lambda: cleanup_tutorial(user_id))
        cleanup_timer.daemon = True  # Make thread daemon so it doesn't block program exit
        cleanup_timer.start()
        
        logger.info(f"✅ Started tutorial for user {user_id}")
        return tutorial_message
        
    except Exception as e:
        logger.error(f"❌ Error starting tutorial: {str(e)}")
        logger.error(f"❌ Exception details: {traceback.format_exc()}")
        
        # Try to send error message if possible
        try:
            # Get chat ID from the message object
            if message and hasattr(message, 'chat') and hasattr(message.chat, 'id'):
                error_chat_id = message.chat.id
                bot.send_message(
                    error_chat_id,
                    "❌ Sorry, there was an error starting the tutorial. Please try again later.",
                    parse_mode='HTML'
                )
            else:
                logger.error("❌ Cannot extract chat_id from message to send error")
        except Exception as error_e:
            # If we can't even send an error message, just log it
            logger.error(f"❌ Could not send error message to user: {error_e}")
        
        return None

def cleanup_tutorial(user_id):
    """Clean up expired tutorial sessions"""
    if user_id in user_tutorial_state:
        if (datetime.now() - user_tutorial_state[user_id]['start_time']).total_seconds() > TUTORIAL_TIMEOUT:
            del user_tutorial_state[user_id]
            logger.info(f"Cleaned up expired tutorial session for user {user_id}")

def handle_tutorial_callback(bot, call):
    """Handle callback queries from tutorial buttons"""
    try:
        # Get necessary IDs
        if not call or not hasattr(call, 'from_user') or not hasattr(call.from_user, 'id'):
            logger.error(f"❌ Invalid call object received in handle_tutorial_callback: {call}")
            return
            
        user_id = call.from_user.id
        
        if not hasattr(call, 'message') or not hasattr(call.message, 'chat') or not hasattr(call.message.chat, 'id'):
            logger.error(f"❌ Invalid message structure in tutorial callback: {call}")
            # Try to answer the callback query at least
            try:
                bot.answer_callback_query(call.id, "Error processing tutorial. Please try again.")
            except:
                pass
            return
            
        chat_id = call.message.chat.id
        
        if not hasattr(call, 'data'):
            logger.error(f"❌ No callback data in tutorial callback")
            return
            
        callback_data = call.data
        
        logger.info(f"📣 Handling tutorial callback {callback_data} from user {user_id}, chat_id {chat_id}")
        
        # Check if user is in tutorial mode
        if user_id not in user_tutorial_state:
            logger.warning(f"⚠️ User {user_id} tried to use tutorial but is not in tutorial mode")
            try:
                bot.answer_callback_query(call.id, "Tutorial session expired. Please start again.")
                # Try to offer to restart tutorial
                try:
                    bot.edit_message_text(
                        "Your tutorial session has expired. Would you like to start again?",
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=InlineKeyboardMarkup().add(
                            InlineKeyboardButton("▶️ Start Tutorial Again", callback_data="help_tutorial"),
                            InlineKeyboardButton("❌ No Thanks", callback_data="tutorial_exit")
                        )
                    )
                except Exception as e:
                    logger.error(f"❌ Error offering to restart tutorial: {e}")
                    # Send as new message instead
                    bot.send_message(
                        chat_id,
                        "Your tutorial session has expired. Would you like to start again?",
                        reply_markup=InlineKeyboardMarkup().add(
                            InlineKeyboardButton("▶️ Start Tutorial Again", callback_data="help_tutorial"),
                            InlineKeyboardButton("❌ No Thanks", callback_data="tutorial_exit")
                        )
                    )
            except Exception as e:
                logger.error(f"❌ Error handling expired tutorial session: {e}")
            return
        
        # At this point we know the user is in a tutorial session
        # Get current step info
        current_step = user_tutorial_state[user_id]['current_step']
        logger.info(f"📋 Current tutorial step for user {user_id}: {current_step}")
        
        try:
            step_info = TUTORIAL_STEPS[current_step]
        except KeyError:
            logger.error(f"❌ Invalid tutorial step: {current_step}. Resetting to start.")
            current_step = 'start'
            user_tutorial_state[user_id]['current_step'] = 'start'
            step_info = TUTORIAL_STEPS['start']
        
        if callback_data == 'tutorial_next':
            # Note: The callback should have already been answered in bot_commands.py
            # but as a safety measure we'll check and answer if needed
            next_step = step_info['next_step']
            if next_step:
                user_tutorial_state[user_id]['current_step'] = next_step
                next_step_info = TUTORIAL_STEPS[next_step]
                
                logger.info(f"➡️ Moving user {user_id} to next tutorial step: {next_step}")
                
                # Double-check that callback was answered (belt-and-suspenders approach)
                try:
                    # CRITICAL: We must answer the callback to clear the loading state
                    # This should already have happened in the callback handler, but just in case
                    # NOTE: Telegram only allows one answer per callback
                    # so if it was already answered, this might fail - that's okay
                    bot.answer_callback_query(call.id)
                    logger.info(f"✅ Callback query double-checked and answered in handle_tutorial_callback")
                except Exception as answer_err:
                    # This might be normal if already answered in bot_commands.py
                    logger.debug(f"Note: Could not answer callback query again (likely already answered): {answer_err}")
                
                # Now edit the message with the new content - separated for better error isolation
                try:
                    # Prepare the new message content
                    keyboard = get_tutorial_keyboard(next_step)
                    content = f"<b>{next_step_info['title']}</b>\n\n{next_step_info['content']}"
                    
                    # Make sure we have a valid message_id
                    message_id = call.message.message_id
                    
                    # Update the message
                    bot.edit_message_text(
                        text=content,
                        chat_id=chat_id,
                        message_id=message_id,
                        parse_mode='HTML',
                        reply_markup=keyboard
                    )
                    logger.info(f"✅ Successfully edited message for tutorial step {next_step}")
                    
                    # Update stored message ID in case it changed
                    user_tutorial_state[user_id]['message_id'] = message_id
                    
                except Exception as e:
                    logger.error(f"❌ Error editing message for tutorial step {next_step}: {e}")
                    logger.error(traceback.format_exc())
                    
                    # Try to send a new message instead
                    try:
                        logger.info(f"Attempting to send new message for tutorial step {next_step}")
                        new_message = bot.send_message(
                            chat_id=chat_id,
                            text=f"<b>{next_step_info['title']}</b>\n\n{next_step_info['content']}",
                            parse_mode='HTML',
                            reply_markup=get_tutorial_keyboard(next_step)
                        )
                        # Update stored message ID
                        if new_message and hasattr(new_message, 'message_id'):
                            user_tutorial_state[user_id]['message_id'] = new_message.message_id
                        logger.info(f"✅ Successfully sent new message for tutorial step {next_step}")
                    except Exception as send_error:
                        logger.error(f"❌ Critical error sending new tutorial message: {send_error}")
                        logger.error(traceback.format_exc())
            else:
                logger.warning(f"⚠️ No next step defined for step {current_step}")
                bot.answer_callback_query(call.id, "You've reached the end of this section")
            
        elif callback_data == 'tutorial_prev':
            # Note: The callback should have already been answered in bot_commands.py
            # but as a safety measure we'll check and answer if needed
            
            # Find previous step
            prev_step = None
            for step, info in TUTORIAL_STEPS.items():
                if info['next_step'] == current_step:
                    prev_step = step
                    user_tutorial_state[user_id]['current_step'] = step
                    
                    logger.info(f"⬅️ Moving user {user_id} to previous tutorial step: {step}")
                    
                    # Double-check that callback was answered (belt-and-suspenders approach)
                    try:
                        # CRITICAL: We must answer the callback to clear the loading state
                        # This should already have happened in the callback handler, but just in case
                        # NOTE: Telegram only allows one answer per callback
                        # so if it was already answered, this might fail - that's okay
                        bot.answer_callback_query(call.id)
                        logger.info(f"✅ Callback query double-checked and answered in handle_tutorial_callback")
                    except Exception as answer_err:
                        # This might be normal if already answered in bot_commands.py
                        logger.debug(f"Note: Could not answer callback query again (likely already answered): {answer_err}")
                    
                    # Now edit the message with the previous step content - separated for better error handling
                    try:
                        # Prepare the message content
                        keyboard = get_tutorial_keyboard(step)
                        content = f"<b>{info['title']}</b>\n\n{info['content']}"
                        
                        # Make sure we have a valid message_id
                        message_id = call.message.message_id
                        
                        # Update the message
                        bot.edit_message_text(
                            text=content,
                            chat_id=chat_id,
                            message_id=message_id,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                        logger.info(f"✅ Successfully edited message for previous tutorial step {step}")
                        
                        # Update stored message ID in case it changed
                        user_tutorial_state[user_id]['message_id'] = message_id
                        
                    except Exception as e:
                        logger.error(f"❌ Error editing message for previous tutorial step {step}: {e}")
                        logger.error(traceback.format_exc())
                        
                        # Try to send a new message instead
                        try:
                            logger.info(f"Attempting to send new message for previous tutorial step {step}")
                            new_message = bot.send_message(
                                chat_id=chat_id,
                                text=f"<b>{info['title']}</b>\n\n{info['content']}",
                                parse_mode='HTML',
                                reply_markup=get_tutorial_keyboard(step)
                            )
                            # Update stored message ID
                            if new_message and hasattr(new_message, 'message_id'):
                                user_tutorial_state[user_id]['message_id'] = new_message.message_id
                            logger.info(f"✅ Successfully sent new message for previous tutorial step {step}")
                        except Exception as send_error:
                            logger.error(f"❌ Critical error sending new tutorial message: {send_error}")
                            logger.error(traceback.format_exc())
                    break
                    
            if not prev_step:
                logger.warning(f"⚠️ No previous step found for step {current_step}")
                bot.answer_callback_query(call.id, "You're at the beginning of the tutorial")
            else:
                bot.answer_callback_query(call.id)
        
        elif callback_data == 'tutorial_exit':
            # End tutorial
            logger.info(f"🚪 User {user_id} is exiting the tutorial")
            
            # Note: The callback should have already been answered in bot_commands.py
            # but as a safety measure we'll check and answer if needed
            try:
                # CRITICAL: We must answer the callback to clear the loading state
                # This should already have happened in the callback handler, but just in case
                bot.answer_callback_query(call.id)
                logger.info(f"✅ Callback query double-checked and answered in exit handler")
            except Exception as answer_err:
                # This might be normal if already answered in bot_commands.py
                logger.debug(f"Note: Could not answer callback query again (likely already answered): {answer_err}")
            
            # Continue with exit process
            from_help = user_tutorial_state[user_id].get('from_help', False)
            
            # Store value and then delete from dict
            try:
                del user_tutorial_state[user_id]
                logger.info(f"✅ Successfully removed user {user_id} from tutorial state")
            except Exception as e:
                logger.error(f"❌ Error removing user from tutorial state: {e}")
            
            # Return to main menu
            try:
                bot.edit_message_text(
                    "✅ <b>Tutorial closed.</b>\n\nYou can restart the tutorial anytime by typing /tutorial or via the Help Center.",
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    parse_mode='HTML'
                )
                logger.info(f"✅ Successfully displayed tutorial exit message to user {user_id}")
            except Exception as e:
                logger.error(f"❌ Error displaying tutorial exit message: {e}")
                # Try to send a new message instead
                try:
                    bot.send_message(
                        chat_id,
                        "✅ <b>Tutorial closed.</b>\n\nYou can restart the tutorial anytime by typing /tutorial or via the Help Center.",
                        parse_mode='HTML'
                    )
                    logger.info(f"✅ Successfully sent new tutorial exit message")
                except Exception as send_error:
                    logger.error(f"❌ Error sending tutorial exit message: {send_error}")
            
            # Return to main menu or help center
            if from_help:
                logger.info(f"🔄 Returning user {user_id} to help center as tutorial was launched from there")
                try:
                    from bot import help_center
                    help_center(call.message)
                    logger.info(f"✅ Successfully returned user {user_id} to help center")
                except Exception as e:
                    logger.error(f"❌ Error returning to help center: {e}")
                    logger.error(f"❌ Exception details: {traceback.format_exc()}")
                    # Fallback to main menu
                    try:
                        from bot import create_main_menu
                        bot.send_message(
                            chat_id,
                            "Returning to main menu...",
                            reply_markup=create_main_menu(chat_id=chat_id)
                        )
                        logger.info(f"✅ Successfully returned user {user_id} to main menu as fallback")
                    except Exception as menu_error:
                        logger.error(f"❌ Error creating main menu: {menu_error}")
                        logger.error(f"❌ Exception details: {traceback.format_exc()}")
                        # Ultimate fallback
                        try:
                            bot.send_message(
                                chat_id,
                                "Please use the menu below to continue.",
                                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                                    KeyboardButton('🏠 Main Menu')
                                )
                            )
                        except Exception as ultimate_error:
                            logger.error(f"❌ Ultimate fallback also failed: {ultimate_error}")
            else:
                logger.info(f"🏠 Returning user {user_id} to main menu")
                try:
                    from bot import create_main_menu
                    bot.send_message(
                        chat_id,
                        "Returning to main menu...",
                        reply_markup=create_main_menu(chat_id=chat_id)
                    )
                    logger.info(f"✅ Successfully returned user {user_id} to main menu")
                except Exception as menu_error:
                    logger.error(f"❌ Error creating main menu: {menu_error}")
                    logger.error(f"❌ Exception details: {traceback.format_exc()}")
                    # Ultimate fallback
                    try:
                        bot.send_message(
                            chat_id,
                            "Please use the menu below to continue.",
                            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                                KeyboardButton('🏠 Main Menu')
                            )
                        )
                    except Exception as ultimate_error:
                        logger.error(f"❌ Ultimate fallback also failed: {ultimate_error}")
        
        elif callback_data == 'tutorial_skip':
            # Skip tutorial
            logger.info(f"⏭️ User {user_id} is skipping the tutorial")
            
            # Note: The callback should have already been answered in bot_commands.py
            # but as a safety measure we'll check and answer if needed
            try:
                # CRITICAL: We must answer the callback to clear the loading state
                # This should already have happened in the callback handler, but just in case
                bot.answer_callback_query(call.id)
                logger.info(f"✅ Callback query double-checked and answered in skip handler")
            except Exception as answer_err:
                # This might be normal if already answered in bot_commands.py
                logger.debug(f"Note: Could not answer callback query again (likely already answered): {answer_err}")
            
            try:
                del user_tutorial_state[user_id]
                logger.info(f"✅ Successfully removed user {user_id} from tutorial state")
            except Exception as e:
                logger.error(f"❌ Error removing user from tutorial state: {e}")
            
            try:
                bot.edit_message_text(
                    "Tutorial skipped. You can start it again anytime by typing /tutorial.",
                    chat_id=chat_id,
                    message_id=call.message.message_id
                )
                logger.info(f"✅ Successfully displayed tutorial skip message")
            except Exception as e:
                logger.error(f"❌ Error displaying tutorial skip message: {e}")
            
            # Return to main menu
            try:
                from bot import create_main_menu
                bot.send_message(
                    chat_id,
                    "Returning to main menu...",
                    reply_markup=create_main_menu(chat_id=chat_id)
                )
                logger.info(f"✅ Successfully returned user to main menu")
            except Exception as menu_error:
                logger.error(f"❌ Error creating main menu: {menu_error}")
                logger.error(f"❌ Exception details: {traceback.format_exc()}")
        
        elif callback_data == 'tutorial_register':
            # Start registration process
            logger.info(f"📝 User {user_id} is starting registration from tutorial")
            
            # Note: The callback should have already been answered in bot_commands.py
            # but as a safety measure we'll check and answer if needed
            try:
                # CRITICAL: We must answer the callback to clear the loading state
                # This should already have happened in the callback handler, but just in case
                bot.answer_callback_query(call.id)
                logger.info(f"✅ Callback query double-checked and answered in register handler")
            except Exception as answer_err:
                # This might be normal if already answered in bot_commands.py
                logger.debug(f"Note: Could not answer callback query again (likely already answered): {answer_err}")
            
            try:
                del user_tutorial_state[user_id]
                logger.info(f"✅ Successfully removed user {user_id} from tutorial state")
            except Exception as e:
                logger.error(f"❌ Error removing user from tutorial state: {e}")
            
            try:
                bot.edit_message_text(
                    "Starting registration process...",
                    chat_id=chat_id,
                    message_id=call.message.message_id
                )
                logger.info(f"✅ Successfully displayed registration transition message")
            except Exception as e:
                logger.error(f"❌ Error displaying registration transition message: {e}")
            
            # Redirect to registration
            try:
                from bot import register_user
                register_user(call.message)
                logger.info(f"✅ Successfully started registration process for user {user_id}")
            except Exception as e:
                logger.error(f"❌ Error starting registration: {e}")
                logger.error(f"❌ Exception details: {traceback.format_exc()}")
                try:
                    bot.send_message(
                        chat_id,
                        "Sorry, there was an error starting registration. Please use the 'Register' button from the main menu."
                    )
                except Exception as send_error:
                    logger.error(f"❌ Error sending registration error message: {send_error}")
        
        elif callback_data == 'tutorial_help':
            # Go to help center
            logger.info(f"❓ User {user_id} is going to help center from tutorial")
            try:
                del user_tutorial_state[user_id]
                logger.info(f"✅ Successfully removed user {user_id} from tutorial state")
            except Exception as e:
                logger.error(f"❌ Error removing user from tutorial state: {e}")
            
            try:
                bot.edit_message_text(
                    "Opening Help Center...",
                    chat_id=chat_id,
                    message_id=call.message.message_id
                )
                logger.info(f"✅ Successfully displayed help center transition message")
            except Exception as e:
                logger.error(f"❌ Error displaying help center transition message: {e}")
            
            # Redirect to help center
            try:
                from bot import help_center
                help_center(call.message)
                logger.info(f"✅ Successfully opened help center for user {user_id}")
            except Exception as e:
                logger.error(f"❌ Error opening help center: {e}")
                logger.error(f"❌ Exception details: {traceback.format_exc()}")
                try:
                    bot.send_message(
                        chat_id,
                        "Sorry, there was an error opening the Help Center. Please use the 'Help Center' button from the main menu."
                    )
                except Exception as send_error:
                    logger.error(f"❌ Error sending help center error message: {send_error}")
            
            try:
                bot.answer_callback_query(call.id)
            except Exception as answer_error:
                logger.error(f"❌ Error answering callback query: {answer_error}")
    
    except Exception as e:
        logger.error(f"❌ Error handling tutorial callback: {e}")
        logger.error(f"❌ Exception details: {traceback.format_exc()}")
        try:
            # Safely answer the callback query if possible
            if 'call' in locals() and hasattr(call, 'id'):
                bot.answer_callback_query(call.id, "An error occurred. Please try again.")
            
            # Attempt to get chat_id from call object and send error message
            if 'call' in locals() and hasattr(call, 'message') and hasattr(call.message, 'chat') and hasattr(call.message.chat, 'id'):
                error_chat_id = call.message.chat.id
                bot.send_message(
                    error_chat_id,
                    "Sorry, there was an error with the tutorial. Please try again later or type /start to return to the main menu."
                )
                logger.info(f"✅ Successfully sent error message to chat {error_chat_id}")
            else:
                logger.error("❌ Could not extract chat_id from call to send error message")
        except Exception as notify_error:
            logger.error(f"❌ Error notifying user of callback error: {notify_error}")

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

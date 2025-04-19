#!/usr/bin/env python3
"""
Bot command handlers for commands that need to be imported into the main bot
"""
import logging
import traceback
import os

logger = logging.getLogger(__name__)

def add_tutorial_handlers(bot):
    """Add tutorial command handlers to the bot"""
    try:
        # Import the tutorial module
        from bot_tutorial import start_tutorial, handle_tutorial_callback
        
        # Add command handler for /tutorial
        @bot.message_handler(commands=['tutorial'])
        def tutorial_command(message):
            """Handle /tutorial command"""
            start_tutorial(bot, message)
        
        # Add callback handler for tutorial navigation buttons
        @bot.callback_query_handler(func=lambda call: call.data.startswith('tutorial_'))
        def tutorial_callbacks(call):
            """Handle tutorial button callbacks"""
            handle_tutorial_callback(bot, call)
            
        # Log success
        logger.info("✅ Tutorial command handlers added successfully")
        return True
    except Exception as e:
        # Log error but don't crash
        logger.error(f"❌ Error setting up tutorial handlers: {e}")
        logger.error(traceback.format_exc())
        return False
        
def setup_help_center_tutorial(bot):
    """Add tutorial option to help center"""
    try:
        # Update the help buttons handler to support tutorial
        original_handle_help_buttons = None
        for handler in bot.callback_query_handlers:
            if getattr(handler['function'], '__name__', '') == 'handle_help_buttons':
                original_handle_help_buttons = handler['function']
                break
        
        if not original_handle_help_buttons:
            logger.error("❌ Could not find original help_buttons handler")
            return False
            
        # Define a new handler that wraps the original one
        def enhanced_help_buttons(call):
            """Enhanced help buttons handler with tutorial support"""
            if call.data == "help_tutorial":
                # Start the tutorial from help center
                try:
                    from bot_tutorial import start_tutorial
                    start_tutorial(bot, call.message, from_help=True)
                    bot.answer_callback_query(call.id)
                except Exception as e:
                    logger.error(f"Error starting tutorial from help center: {e}")
                    bot.answer_callback_query(call.id, "Tutorial currently unavailable")
            else:
                # Call the original handler for all other help buttons
                original_handle_help_buttons(call)
                
        # Replace the original handler with our enhanced one
        for i, handler in enumerate(bot.callback_query_handlers):
            if handler.get('function', None) == original_handle_help_buttons:
                bot.callback_query_handlers[i]['function'] = enhanced_help_buttons
                logger.info("✅ Help center tutorial integration added")
                return True
                
        logger.error("❌ Could not replace help buttons handler")
        return False
        
    except Exception as e:
        logger.error(f"❌ Error setting up help center tutorial: {e}")
        logger.error(traceback.format_exc())
        return False

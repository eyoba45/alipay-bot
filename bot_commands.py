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
            try:
                logger.info(f"📣 Tutorial command received from user {message.from_user.id}")
                tutorial_result = start_tutorial(bot, message)
                if tutorial_result:
                    logger.info(f"✅ Tutorial started successfully for user {message.from_user.id}")
                else:
                    logger.warning(f"⚠️ Tutorial didn't start properly for user {message.from_user.id}")
            except Exception as e:
                logger.error(f"❌ Error in tutorial command handler: {e}")
                logger.error(traceback.format_exc())
                # Try to notify user
                try:
                    bot.send_message(
                        message.chat.id,
                        "Sorry, there was an error starting the tutorial. Please try again later.",
                        parse_mode='HTML'
                    )
                except:
                    pass
        
        # Add callback handler for tutorial navigation buttons with high priority
        @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith('tutorial_'), priority=100)
        def tutorial_callbacks(call):
            """Handle tutorial button callbacks"""
            try:
                logger.info(f"📣 Tutorial callback received: {call.data} from user {call.from_user.id}")
                handle_tutorial_callback(bot, call)
                logger.info(f"✅ Tutorial callback processed successfully: {call.data}")
            except Exception as e:
                logger.error(f"❌ Error in tutorial callback handler: {e}")
                logger.error(traceback.format_exc())
                # Try to notify user
                try:
                    bot.answer_callback_query(
                        call.id,
                        "Sorry, there was an error processing your request. Please try again.",
                        show_alert=True
                    )
                except:
                    pass
            
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
        # We'll add a direct handler for the help tutorial button to ensure it's reliably handled
        @bot.callback_query_handler(func=lambda call: call.data == "help_tutorial", priority=200)
        def help_tutorial_button(call):
            """Direct handler for help tutorial button with high priority"""
            try:
                logger.info(f"📣 Help tutorial button clicked by user {call.from_user.id}")
                # Try to answer the callback query to prevent loading indicator
                try:
                    bot.answer_callback_query(call.id)
                except Exception as cb_err:
                    logger.error(f"❌ Error answering callback query: {cb_err}")
                
                # Start the tutorial
                from bot_tutorial import start_tutorial
                result = start_tutorial(bot, call.message, from_help=True)
                if result:
                    logger.info(f"✅ Tutorial started successfully from help center for user {call.from_user.id}")
                else:
                    logger.warning(f"⚠️ Tutorial start returned None for user {call.from_user.id}")
                    # Try to notify user
                    bot.send_message(
                        call.message.chat.id, 
                        "Sorry, there was an issue starting the tutorial. Please try again by typing /tutorial",
                        parse_mode='HTML'
                    )
            except Exception as e:
                logger.error(f"❌ Error handling help_tutorial button: {e}")
                logger.error(traceback.format_exc())
                # Try to notify user
                try:
                    bot.answer_callback_query(
                        call.id,
                        "Sorry, there was an error starting the tutorial. Please try again by typing /tutorial",
                        show_alert=True
                    )
                except:
                    pass
        
        # For backward compatibility, also update the general help buttons handler if it exists
        try:
            original_handle_help_buttons = None
            for handler in bot.callback_query_handlers:
                if getattr(handler.get('function'), '__name__', '') == 'handle_help_buttons':
                    original_handle_help_buttons = handler['function']
                    break
            
            if original_handle_help_buttons:
                # Define a new handler that wraps the original one
                def enhanced_help_buttons(call):
                    """Enhanced help buttons handler with tutorial support"""
                    if call.data == "help_tutorial":
                        # This should be handled by the dedicated handler above
                        # but just in case, we'll handle it here too
                        logger.info(f"⚠️ Help tutorial button handled by general handler for user {call.from_user.id}")
                        try:
                            from bot_tutorial import start_tutorial
                            start_tutorial(bot, call.message, from_help=True)
                            bot.answer_callback_query(call.id)
                        except Exception as e:
                            logger.error(f"❌ Error starting tutorial from help center: {e}")
                            bot.answer_callback_query(call.id, "Tutorial currently unavailable")
                    else:
                        # Call the original handler for all other help buttons
                        original_handle_help_buttons(call)
                    
                # Replace the original handler with our enhanced one
                for i, handler in enumerate(bot.callback_query_handlers):
                    if handler.get('function', None) == original_handle_help_buttons:
                        bot.callback_query_handlers[i]['function'] = enhanced_help_buttons
                        logger.info("✅ Enhanced existing help buttons handler")
                        break
        except Exception as handler_err:
            logger.error(f"❌ Error updating existing help button handler: {handler_err}")
            # Non-critical error, we can continue
        
        logger.info("✅ Help center tutorial integration added")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error setting up help center tutorial: {e}")
        logger.error(traceback.format_exc())
        return False

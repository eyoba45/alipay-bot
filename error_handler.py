#!/usr/bin/env python3
"""
Advanced Error Handler for Telegram Bot
Provides robust error recovery and reporting
"""
import logging
import sys
import time
import traceback
import threading
from functools import wraps
from datetime import datetime
from collections import defaultdict, deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ErrorHandler:
    """Advanced error handler with recovery capabilities"""
    
    def __init__(self, max_consecutive_errors=5, cooldown_period=60):
        self.max_consecutive_errors = max_consecutive_errors
        self.cooldown_period = cooldown_period
        
        # Error tracking
        self.error_counts = defaultdict(int)  # Count errors by handler
        self.consecutive_errors = defaultdict(int)  # Count consecutive errors by handler
        self.last_error_time = defaultdict(float)  # Last error time by handler
        self.error_history = defaultdict(lambda: deque(maxlen=10))  # Keep last 10 errors
        
        # Global error tracking
        self.total_errors = 0
        self.total_handled = 0
        self.error_lock = threading.Lock()
        
        # Handler blocking
        self.blocked_handlers = set()
        self.block_expiry = {}
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(
            target=self._monitor_blocked_handlers,
            name="ErrorMonitor",
            daemon=True
        )
        self.monitor_thread.start()
        
        logger.info("ErrorHandler initialized")
        
    def handle_error(self, handler_name, error, user_id=None, message=None):
        """Handle an error and decide if the handler should be temporarily blocked"""
        with self.error_lock:
            self.total_errors += 1
            self.error_counts[handler_name] += 1
            self.consecutive_errors[handler_name] += 1
            self.last_error_time[handler_name] = time.time()
            
            # Add to history
            error_info = {
                'timestamp': datetime.now(),
                'error': str(error),
                'traceback': traceback.format_exc(),
                'user_id': user_id
            }
            self.error_history[handler_name].append(error_info)
            
            # Check if we should block the handler
            should_block = self.consecutive_errors[handler_name] >= self.max_consecutive_errors
            
            if should_block and handler_name not in self.blocked_handlers:
                block_until = time.time() + self.cooldown_period
                self.blocked_handlers.add(handler_name)
                self.block_expiry[handler_name] = block_until
                
                logger.warning(f"⚠️ Handler '{handler_name}' blocked for {self.cooldown_period}s due to {self.consecutive_errors[handler_name]} consecutive errors")
                
            return should_block
            
    def is_handler_blocked(self, handler_name):
        """Check if a handler is currently blocked"""
        if handler_name not in self.blocked_handlers:
            return False
            
        # Check if block has expired
        expiry = self.block_expiry.get(handler_name, 0)
        if expiry <= time.time():
            # Block expired, unblock the handler
            with self.error_lock:
                if handler_name in self.blocked_handlers:
                    self.blocked_handlers.remove(handler_name)
                    self.consecutive_errors[handler_name] = 0
                    logger.info(f"✅ Handler '{handler_name}' unblocked after cooldown period")
                    
            return False
            
        return True
        
    def reset_handler(self, handler_name):
        """Reset error counts for a handler after successful execution"""
        with self.error_lock:
            self.consecutive_errors[handler_name] = 0
            
    def get_error_report(self):
        """Generate an error report for all handlers"""
        with self.error_lock:
            report = {
                'total_errors': self.total_errors,
                'total_handled': self.total_handled,
                'blocked_handlers': list(self.blocked_handlers),
                'handler_errors': {
                    handler: {
                        'count': self.error_counts[handler],
                        'consecutive': self.consecutive_errors[handler],
                        'last_error': datetime.fromtimestamp(self.last_error_time[handler]).strftime('%Y-%m-%d %H:%M:%S') if self.last_error_time[handler] > 0 else 'never',
                        'blocked_until': datetime.fromtimestamp(self.block_expiry.get(handler, 0)).strftime('%Y-%m-%d %H:%M:%S') if handler in self.blocked_handlers else 'not blocked'
                    }
                    for handler in self.error_counts
                }
            }
            return report
            
    def _monitor_blocked_handlers(self):
        """Periodically check and unblock handlers that have expired"""
        while True:
            try:
                time.sleep(15)  # Check every 15 seconds
                
                current_time = time.time()
                with self.error_lock:
                    # Create a list of handlers to unblock
                    to_unblock = [
                        handler for handler in self.blocked_handlers
                        if self.block_expiry.get(handler, 0) <= current_time
                    ]
                    
                    # Unblock them
                    for handler in to_unblock:
                        self.blocked_handlers.remove(handler)
                        self.consecutive_errors[handler] = 0
                        logger.info(f"✅ Handler '{handler}' automatically unblocked after cooldown period")
                        
            except Exception as e:
                logger.error(f"Error in error monitor: {e}")
                
# Create a global error handler instance
error_handler = ErrorHandler()

def safe_handler(func):
    """
    Decorator for safely handling errors in Telegram message handlers
    """
    handler_name = func.__name__
    
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        # Check if handler is blocked
        if error_handler.is_handler_blocked(handler_name):
            logger.warning(f"Skipping blocked handler: {handler_name}")
            return
            
        # Get user ID for tracking
        user_id = None
        if hasattr(message, 'from_user') and hasattr(message.from_user, 'id'):
            user_id = message.from_user.id
            
        try:
            # Run the handler
            result = func(message, *args, **kwargs)
            
            # Reset consecutive error count on success
            error_handler.reset_handler(handler_name)
            
            return result
        except Exception as e:
            # Log the error
            logger.error(f"Error in handler {handler_name}: {e}")
            logger.error(traceback.format_exc())
            
            # Handle the error
            error_handler.handle_error(handler_name, e, user_id, message)
            
            # Try to send an error message to the user
            try:
                if hasattr(message, 'chat') and hasattr(message.chat, 'id'):
                    chat_id = message.chat.id
                    # Import lazily to avoid circular imports
                    import telebot
                    from telebot.apihelper import ApiTelegramException
                    
                    # Get bot instance (assuming it's a global variable in the main module)
                    # This is a best effort approach, might not always work
                    import sys
                    for module in sys.modules.values():
                        if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                            bot = module.bot
                            try:
                                bot.send_message(
                                    chat_id,
                                    "Sorry, I encountered an error processing your request. Please try again later."
                                )
                            except ApiTelegramException:
                                # Could not send message to user
                                pass
                            break
            except Exception as notify_error:
                logger.error(f"Failed to notify user of error: {notify_error}")
                
    return wrapper

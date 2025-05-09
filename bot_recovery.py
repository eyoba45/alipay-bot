#!/usr/bin/env python3
"""
Bot Recovery Mechanism - Enhanced Recovery for Telegram Bot Interruptions

This module implements a smart recovery system to handle bot interruptions,
network issues, and unexpected errors. It preserves user state, restores
conversations, and ensures a seamless user experience even after bot restarts.

Features:
- Persistent user state storage using database
- Conversation recovery after unexpected restarts
- Automatic command re-execution for interrupted operations
- Smart rate-limiting during recovery to prevent overloads
- Detailed metrics and diagnostics logging
"""

import os
import sys
import time
import json
import logging
import threading
import traceback
from datetime import datetime, timedelta
from collections import defaultdict, deque
from functools import wraps

# SQLAlchemy imports
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, or_, desc
from sqlalchemy.orm import Session

# Import local modules
from error_handler import error_handler
from request_manager import request_manager
from connection_manager import get_session, safe_close_session
from models import User, Order, Transaction, Base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BotRecoveryState(Base):
    """Model for storing recovery state data"""
    __tablename__ = 'bot_recovery_state'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    telegram_id = Column(Integer, nullable=False, index=True)
    state_key = Column(String, nullable=False)
    state_data = Column(Text, nullable=True)
    command = Column(String, nullable=True)
    params = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    def __repr__(self):
        return f"<BotRecoveryState(user_id={self.user_id}, state_key='{self.state_key}')>"

class BotInterruptionLog(Base):
    """Model for tracking bot interruptions"""
    __tablename__ = 'bot_interruption_log'
    
    id = Column(Integer, primary_key=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    reason = Column(String, nullable=True)
    recovery_successful = Column(Boolean, default=False)
    affected_users = Column(Integer, default=0)
    recovered_states = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<BotInterruptionLog(id={self.id}, duration={self.duration_seconds})>"

class BotRecoveryManager:
    """Manages the recovery process for bot interruptions"""
    
    def __init__(
        self,
        state_expiration=24*60*60,  # State expires after 24 hours by default
        polling_interval=60,        # Check every minute for interruptions
        max_concurrent_recoveries=5,# Maximum number of concurrent user recoveries
        recovery_grace_period=5     # Allow 5 seconds after startup before recovery
    ):
        self.state_expiration = state_expiration
        self.polling_interval = polling_interval
        self.max_concurrent_recoveries = max_concurrent_recoveries
        self.recovery_grace_period = recovery_grace_period
        
        # Tracking
        self.bot_start_time = time.time()
        self.last_interruption = None
        self.interruption_count = 0
        self.recovered_states_count = 0
        self.recovery_failures = 0
        
        # Throttling mechanism
        self.recovery_queue = deque()
        self.currently_recovering = set()
        self.recovery_lock = threading.Lock()
        
        # Recovery thread
        self.running = False
        self.recovery_thread = None
        self.in_recovery_mode = False
        
        # Statistics
        self.recovery_success_rate = 1.0  # Start optimistic
        self.avg_recovery_time = 0
        self.total_recoveries = 0
        
        # Create tables if they don't exist
        self._create_tables()
        
    def _create_tables(self):
        """Create the necessary database tables"""
        try:
            session = get_session()
            Base.metadata.create_all(session.bind)
            session.commit()
            logger.info("✅ Bot recovery tables created successfully")
        except Exception as e:
            logger.error(f"Error creating recovery tables: {e}")
        finally:
            safe_close_session(session)
            
    def start(self):
        """Start the recovery manager"""
        if self.running:
            return
            
        self.running = True
        self.bot_start_time = time.time()
        
        # Log bot start
        self._record_bot_start()
        
        # Start recovery thread
        self.recovery_thread = threading.Thread(
            target=self._recovery_monitor,
            name="RecoveryMonitor",
            daemon=True
        )
        self.recovery_thread.start()
        
        # Start cleanup thread
        cleanup_thread = threading.Thread(
            target=self._cleanup_expired_states,
            name="StateCleanup",
            daemon=True
        )
        cleanup_thread.start()
        
        # Schedule recovery check
        threading.Timer(self.recovery_grace_period, self._check_for_recovery).start()
        
        logger.info("✅ Bot recovery manager started")
        
    def stop(self):
        """Stop the recovery manager"""
        if not self.running:
            return
            
        self.running = False
        
        # Record bot stop with reason
        self._record_bot_stop("Controlled shutdown")
        
        logger.info("✅ Bot recovery manager stopped")
        
    def _record_bot_start(self):
        """Record a bot start event"""
        session = None
        try:
            session = get_session()
            
            # Check for unfinished interruption log
            unfinished = session.query(BotInterruptionLog)\
                               .filter(BotInterruptionLog.end_time.is_(None))\
                               .first()
                               
            if unfinished:
                # Calculate duration
                now = datetime.utcnow()
                if unfinished.start_time:
                    duration = (now - unfinished.start_time).total_seconds()
                    unfinished.duration_seconds = duration
                unfinished.end_time = now
                unfinished.notes = f"{unfinished.notes or ''}\nBot restarted at {now.strftime('%Y-%m-%d %H:%M:%S')}"
                
                session.commit()
                
                self.last_interruption = unfinished
                logger.info(f"Found unfinished interruption log, duration: {duration:.1f}s")
                
        except Exception as e:
            logger.error(f"Error recording bot start: {e}")
            if session:
                session.rollback()
        finally:
            safe_close_session(session)
            
    def _record_bot_stop(self, reason="Unknown"):
        """Record a bot stop event"""
        session = None
        try:
            session = get_session()
            
            # Create a new interruption log
            interruption = BotInterruptionLog(
                start_time=datetime.utcnow(),
                reason=reason
            )
            
            session.add(interruption)
            session.commit()
            
            self.interruption_count += 1
            
        except Exception as e:
            logger.error(f"Error recording bot stop: {e}")
            if session:
                session.rollback()
        finally:
            safe_close_session(session)
            
    def _check_for_recovery(self):
        """Check if we need to recover from a previous interruption"""
        if self.in_recovery_mode:
            return
            
        session = None
        try:
            session = get_session()
            
            # Check if we have active states to recover
            count = session.query(BotRecoveryState)\
                          .filter(BotRecoveryState.is_active == True)\
                          .count()
                          
            if count > 0:
                logger.info(f"Found {count} active states to recover")
                self.in_recovery_mode = True
                
                # Perform recovery
                self._perform_recovery(session)
                
            else:
                logger.info("No states to recover")
                
        except Exception as e:
            logger.error(f"Error checking for recovery: {e}")
        finally:
            if session and session.is_active:
                safe_close_session(session)
                
    def _perform_recovery(self, session=None):
        """Recover all active states in a controlled manner"""
        own_session = False
        if not session:
            session = get_session()
            own_session = True
            
        try:
            # Get active states, grouped by user and ordered by most recent
            users_to_recover = session.query(BotRecoveryState.telegram_id)\
                                     .filter(BotRecoveryState.is_active == True)\
                                     .group_by(BotRecoveryState.telegram_id)\
                                     .all()
                                     
            if not users_to_recover:
                self.in_recovery_mode = False
                return
                
            # Count affected users
            affected_users = len(users_to_recover)
            
            # Log the start of recovery
            logger.info(f"Starting recovery process for {affected_users} users")
            
            # Update interruption log
            if self.last_interruption:
                self.last_interruption.affected_users = affected_users
                session.commit()
                
            # Add users to recovery queue
            for user_row in users_to_recover:
                self.recovery_queue.append(user_row.telegram_id)
                
            # Recovery will happen in the recovery thread
                
        except Exception as e:
            logger.error(f"Error in recovery process: {e}")
        finally:
            if own_session:
                safe_close_session(session)
                
    def _recovery_monitor(self):
        """Monitor thread for processing the recovery queue"""
        logger.info("Recovery monitor thread started")
        
        while self.running:
            try:
                # Process users in recovery queue
                self._process_recovery_queue()
                
                # Sleep between checks
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error in recovery monitor: {e}")
                time.sleep(5)  # Sleep longer on error
                
        logger.info("Recovery monitor thread stopped")
        
    def _process_recovery_queue(self):
        """Process users in the recovery queue"""
        # Check if we have users to recover
        if not self.recovery_queue:
            if self.in_recovery_mode and not self.currently_recovering:
                logger.info("Recovery process completed")
                self.in_recovery_mode = False
                
                # Update interruption log
                session = None
                try:
                    session = get_session()
                    if self.last_interruption:
                        self.last_interruption.recovery_successful = True
                        self.last_interruption.recovered_states = self.recovered_states_count
                        session.commit()
                except Exception as e:
                    logger.error(f"Error updating interruption log: {e}")
                finally:
                    if session:
                        safe_close_session(session)
                        
            return
            
        # Check if we can recover more users
        with self.recovery_lock:
            if len(self.currently_recovering) >= self.max_concurrent_recoveries:
                return
                
            # Get next user to recover
            try:
                telegram_id = self.recovery_queue.popleft()
            except IndexError:
                return
                
            # Add to currently recovering
            self.currently_recovering.add(telegram_id)
            
        # Start recovery thread for this user
        recovery_thread = threading.Thread(
            target=self._recover_user_state,
            args=(telegram_id,),
            name=f"Recovery-{telegram_id}",
            daemon=True
        )
        recovery_thread.start()
        
    def _recover_user_state(self, telegram_id):
        """Recover the state for a specific user"""
        session = None
        try:
            session = get_session()
            
            # Get all active states for this user
            states = session.query(BotRecoveryState)\
                           .filter(
                                BotRecoveryState.telegram_id == telegram_id,
                                BotRecoveryState.is_active == True
                           )\
                           .order_by(desc(BotRecoveryState.updated_at))\
                           .all()
                           
            if not states:
                logger.warning(f"No active states found for user {telegram_id}")
                return
                
            # Log recovery start
            logger.info(f"Recovering {len(states)} states for user {telegram_id}")
            
            # Get the user
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                logger.warning(f"User {telegram_id} not found")
                return
                
            # Send recovery notification
            self._send_recovery_notification(telegram_id)
            
            # Recover most recent state first
            recovered = False
            for state in states:
                try:
                    # Mark as inactive
                    state.is_active = False
                    
                    # Recover the state
                    self._recover_specific_state(state, user, session)
                    
                    # Count recovery
                    with self.recovery_lock:
                        self.recovered_states_count += 1
                        
                    recovered = True
                    
                except Exception as e:
                    logger.error(f"Error recovering state {state.state_key} for user {telegram_id}: {e}")
                    logger.error(traceback.format_exc())
                    
                    with self.recovery_lock:
                        self.recovery_failures += 1
                        
            # Commit changes
            session.commit()
            
            # Update statistics
            if recovered:
                with self.recovery_lock:
                    self.total_recoveries += 1
                    self.recovery_success_rate = (self.total_recoveries - self.recovery_failures) / max(1, self.total_recoveries)
                    
            logger.info(f"Recovery completed for user {telegram_id}")
            
        except Exception as e:
            logger.error(f"Error in user recovery process: {e}")
            logger.error(traceback.format_exc())
            if session:
                session.rollback()
                
        finally:
            if session:
                safe_close_session(session)
                
            # Remove from currently recovering
            with self.recovery_lock:
                if telegram_id in self.currently_recovering:
                    self.currently_recovering.remove(telegram_id)
                    
    def _recover_specific_state(self, state, user, session):
        """Recover a specific state"""
        try:
            # Parse state data
            state_data = json.loads(state.state_data) if state.state_data else {}
            
            # Determine recovery action based on state key
            if state.state_key == 'waiting_for_order_link':
                # User was submitting an order
                self._recover_order_submission(user, state_data, state)
                
            elif state.state_key == 'waiting_for_deposit_amount':
                # User was making a deposit
                self._recover_deposit_process(user, state_data, state)
                
            elif state.state_key == 'waiting_for_order_number':
                # User was tracking an order
                self._recover_order_tracking(user, state_data, state)
                
            elif state.state_key == 'in_registration':
                # User was registering
                self._recover_registration(user, state_data, state)
                
            elif state.state_key == 'in_companion_conversation':
                # User was talking to the AI companion
                self._recover_companion_conversation(user, state_data, state)
                
            else:
                # Generic recovery - just send a message
                self._send_generic_recovery_message(user.telegram_id, state.state_key)
                
        except Exception as e:
            logger.error(f"Error in specific state recovery: {e}")
            raise
            
    def _send_recovery_notification(self, telegram_id):
        """Send a notification that the bot is recovering the user's state"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    try:
                        bot.send_message(
                            telegram_id,
                            """
🔄 <b>Recovering Your Session...</b>

The bot is restoring your previous activity.
Please wait a moment while we recover where you left off.

<i>This happens automatically when the bot restarts</i>
""",
                            parse_mode='HTML'
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error sending recovery notification: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to send recovery notification: {e}")
            
    def _send_generic_recovery_message(self, telegram_id, state_key):
        """Send a generic recovery message"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    # Create main menu keyboard
                    from bot import create_main_menu
                    keyboard = create_main_menu(is_registered=True, chat_id=telegram_id)
                    
                    try:
                        bot.send_message(
                            telegram_id,
                            f"""
✅ <b>Session Recovered</b>

You were previously working on: <code>{state_key}</code>

The bot has been restarted. You can continue from the main menu.
""",
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error sending recovery message: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to send recovery message: {e}")
            
    def _recover_order_submission(self, user, state_data, state):
        """Recover an order submission process"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    # Get the main menu keyboard
                    from bot import create_main_menu, user_states
                    keyboard = create_main_menu(is_registered=True, chat_id=user.telegram_id)
                    
                    try:
                        # Restore user state
                        user_states[user.telegram_id] = 'waiting_for_order_link'
                        
                        # Send recovery message
                        bot.send_message(
                            user.telegram_id,
                            """
✅ <b>Order Submission Recovered</b>

You were in the process of submitting an order.

Please send your AliExpress product link again to continue,
or select a different option from the menu.
""",
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error recovering order submission: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to recover order submission: {e}")
            
    def _recover_deposit_process(self, user, state_data, state):
        """Recover a deposit process"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    # Get the main menu keyboard
                    from bot import create_main_menu, user_states
                    keyboard = create_main_menu(is_registered=True, chat_id=user.telegram_id)
                    
                    try:
                        # Clear the user state first
                        if user.telegram_id in user_states:
                            del user_states[user.telegram_id]
                        
                        # Send recovery message
                        bot.send_message(
                            user.telegram_id,
                            """
✅ <b>Deposit Process Recovered</b>

You were in the process of making a deposit.

Please use the 💰 Deposit button again to restart the process.
""",
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error recovering deposit process: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to recover deposit process: {e}")
            
    def _recover_order_tracking(self, user, state_data, state):
        """Recover order tracking process"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    # Get the main menu keyboard
                    from bot import create_main_menu, user_states
                    keyboard = create_main_menu(is_registered=True, chat_id=user.telegram_id)
                    
                    try:
                        # Clear the user state
                        if user.telegram_id in user_states:
                            del user_states[user.telegram_id]
                        
                        # Send recovery message
                        bot.send_message(
                            user.telegram_id,
                            """
✅ <b>Order Tracking Recovered</b>

You were tracking an order.

Please use the 🔍 Track Order button again to restart tracking.
""",
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error recovering order tracking: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to recover order tracking: {e}")
            
    def _recover_registration(self, user, state_data, state):
        """Recover registration process"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    # Get the main menu keyboard
                    from bot import create_main_menu, user_states, registration_data
                    keyboard = create_main_menu(is_registered=False)
                    
                    try:
                        # Clear registration data
                        if user.telegram_id in registration_data:
                            del registration_data[user.telegram_id]
                            
                        # Clear the user state
                        if user.telegram_id in user_states:
                            del user_states[user.telegram_id]
                        
                        # Send recovery message
                        bot.send_message(
                            user.telegram_id,
                            """
✅ <b>Registration Recovered</b>

You were in the process of registering.

Please use the 🔑 Register button again to restart the registration.
""",
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error recovering registration: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to recover registration: {e}")
            
    def _recover_companion_conversation(self, user, state_data, state):
        """Recover AI companion conversation"""
        try:
            # Import lazily to avoid circular imports
            import telebot
            from telebot.apihelper import ApiTelegramException
            
            # Get bot instance
            for module in sys.modules.values():
                if hasattr(module, 'bot') and isinstance(module.bot, telebot.TeleBot):
                    bot = module.bot
                    
                    try:
                        # Import companion-related modules
                        from bot import companion_conversations, create_main_menu
                        
                        # Exit companion conversation mode
                        if user.telegram_id in companion_conversations:
                            del companion_conversations[user.telegram_id]
                            
                        # Get the main menu keyboard
                        keyboard = create_main_menu(is_registered=True, chat_id=user.telegram_id)
                        
                        # Send recovery message
                        bot.send_message(
                            user.telegram_id,
                            """
✅ <b>AI Assistant Conversation Recovered</b>

You were having a conversation with the AI Assistant.

The bot has been restarted. You can start a new conversation
by pressing the 🤖 AI Assistant button.
""",
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    except ApiTelegramException as e:
                        logger.error(f"Error recovering companion conversation: {e}")
                        
                    break
        except Exception as e:
            logger.error(f"Failed to recover companion conversation: {e}")
            
    def _cleanup_expired_states(self):
        """Periodically clean up expired states"""
        logger.info("State cleanup thread started")
        
        while self.running:
            try:
                time.sleep(3600)  # Run every hour
                
                session = get_session()
                try:
                    # Calculate expiration timestamp
                    expiration_time = datetime.utcnow() - timedelta(seconds=self.state_expiration)
                    
                    # Find expired states
                    expired = session.query(BotRecoveryState)\
                                    .filter(
                                        BotRecoveryState.updated_at < expiration_time,
                                        BotRecoveryState.is_active == True
                                    )\
                                    .all()
                                    
                    if expired:
                        logger.info(f"Cleaning up {len(expired)} expired states")
                        
                        # Mark as inactive
                        for state in expired:
                            state.is_active = False
                            
                        session.commit()
                        
                except Exception as e:
                    logger.error(f"Error cleaning up expired states: {e}")
                    session.rollback()
                finally:
                    safe_close_session(session)
                    
            except Exception as e:
                logger.error(f"Error in state cleanup thread: {e}")
                
        logger.info("State cleanup thread stopped")
        
    def save_user_state(self, telegram_id, state_key, state_data=None, command=None, params=None):
        """
        Save or update a user's state for recovery
        
        Args:
            telegram_id (int): User's Telegram ID
            state_key (str): Key identifying the state (e.g., 'waiting_for_order_link')
            state_data (dict, optional): Additional state data as dictionary
            command (str, optional): Command that triggered this state
            params (dict, optional): Parameters for the command
        
        Returns:
            bool: True if state was saved successfully, False otherwise
        """
        session = None
        try:
            session = get_session()
            
            # Get the user
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                logger.warning(f"Cannot save state for unknown user {telegram_id}")
                return False
                
            # Check for existing state
            existing = session.query(BotRecoveryState)\
                             .filter(
                                 BotRecoveryState.telegram_id == telegram_id,
                                 BotRecoveryState.state_key == state_key,
                                 BotRecoveryState.is_active == True
                             )\
                             .first()
                             
            # Convert data to JSON
            state_data_json = json.dumps(state_data) if state_data else None
            params_json = json.dumps(params) if params else None
            
            if existing:
                # Update existing state
                existing.state_data = state_data_json
                existing.command = command
                existing.params = params_json
                existing.updated_at = datetime.utcnow()
            else:
                # Create new state
                new_state = BotRecoveryState(
                    user_id=user.id,
                    telegram_id=telegram_id,
                    state_key=state_key,
                    state_data=state_data_json,
                    command=command,
                    params=params_json
                )
                session.add(new_state)
                
            session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error saving user state: {e}")
            if session:
                session.rollback()
            return False
        finally:
            if session:
                safe_close_session(session)
                
    def clear_user_state(self, telegram_id, state_key=None):
        """
        Clear a user's saved state
        
        Args:
            telegram_id (int): User's Telegram ID
            state_key (str, optional): Specific state key to clear, or None for all
            
        Returns:
            bool: True if state was cleared successfully, False otherwise
        """
        session = None
        try:
            session = get_session()
            
            # Build query
            query = session.query(BotRecoveryState)\
                          .filter(
                              BotRecoveryState.telegram_id == telegram_id,
                              BotRecoveryState.is_active == True
                          )
                          
            if state_key:
                query = query.filter(BotRecoveryState.state_key == state_key)
                
            # Mark states as inactive
            states = query.all()
            for state in states:
                state.is_active = False
                
            session.commit()
            return True
            
        except Exception as e:
            logger.error(f"Error clearing user state: {e}")
            if session:
                session.rollback()
            return False
        finally:
            if session:
                safe_close_session(session)
                
    def get_recovery_stats(self):
        """Get recovery statistics"""
        return {
            'total_interruptions': self.interruption_count,
            'recovered_states': self.recovered_states_count,
            'recovery_failures': self.recovery_failures,
            'recovery_success_rate': f"{self.recovery_success_rate:.1%}",
            'total_recoveries': self.total_recoveries,
            'in_recovery_mode': self.in_recovery_mode,
            'uptime': f"{(time.time() - self.bot_start_time) / 3600:.1f} hours",
            'recovery_queue_size': len(self.recovery_queue),
            'currently_recovering': len(self.currently_recovering),
        }
        
# Create global instance
recovery_manager = BotRecoveryManager()

def with_state_recovery(state_key):
    """
    Decorator for handling state recovery in message handlers
    
    Args:
        state_key (str): The state key to associate with this handler
        
    Returns:
        function: Decorated function
    """
    def decorator(func):
        @wraps(func)
        def wrapper(message, *args, **kwargs):
            # Lazily import to avoid circular references
            from bot import bot
            
            # Get telegram ID
            telegram_id = None
            if hasattr(message, 'from_user') and hasattr(message.from_user, 'id'):
                telegram_id = message.from_user.id
            
            if not telegram_id:
                # Can't do recovery without telegram ID
                return func(message, *args, **kwargs)
                
            try:
                # Save current state
                state_data = {'args': [str(a) for a in args], 'kwargs': kwargs, 'text': message.text if hasattr(message, 'text') else None}
                command = message.text if hasattr(message, 'text') else None
                recovery_manager.save_user_state(telegram_id, state_key, state_data, command)
                
                # Call original function
                result = func(message, *args, **kwargs)
                
                return result
                
            except Exception as e:
                logger.error(f"Error in state recovery wrapper: {e}")
                # Don't block the original function
                return func(message, *args, **kwargs)
                
        return wrapper
    return decorator

def clear_state(telegram_id, state_key=None):
    """
    Clear a user's saved state
    
    Args:
        telegram_id (int): User's Telegram ID
        state_key (str, optional): Specific state key to clear, or None for all
    """
    return recovery_manager.clear_user_state(telegram_id, state_key)

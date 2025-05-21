#!/usr/bin/env python3
"""
Admin Panel Handlers - Simplified and Improved

This module contains all the admin-related functionality for the Telegram bot,
including user management, order management, deposit management, and system statistics.
It provides a clean, well-structured, and reliable admin experience.
"""

import logging
import traceback
from datetime import datetime, timedelta
import os
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from models import User, Order, PendingDeposit, Transaction
from database import get_session, safe_close_session
from sqlalchemy import func, text, desc, asc
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# Get admin IDs from environment variable
ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_CHAT_ID', '').split(',') if id.strip()]

# States for admin interactions
admin_states = {}

# Pagination settings and storage
ITEMS_PER_PAGE = 5
pagination_data = {}

class AdminSection:
    """Base class for admin sections"""
    
    @staticmethod
    def is_admin(chat_id):
        """Check if a user is an admin"""
        return chat_id in ADMIN_IDS
    
    @staticmethod
    def create_admin_menu():
        """Create the admin dashboard menu"""
        admin_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        admin_menu.add(
            KeyboardButton('👥 User Management'),
            KeyboardButton('📦 Order Management')
        )
        admin_menu.add(
            KeyboardButton('💰 Deposit Management'),
            KeyboardButton('📊 System Stats')
        )
        admin_menu.add(
            KeyboardButton('📅 Subscription Management'),
            KeyboardButton('🔙 Back to Main Menu')
        )
        return admin_menu
    
    @staticmethod
    def handle_admin_dashboard(bot, message):
        """Show admin dashboard with all admin features"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            bot.send_message(
                chat_id,
                "⚠️ You don't have permission to access the admin dashboard."
            )
            return
        
        # Clear any previous admin state
        if chat_id in admin_states:
            del admin_states[chat_id]
            
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔐 <b>ADMIN DASHBOARD</b> 🔐  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Welcome to the Admin Dashboard! Select a management option:

<b>Available Features:</b>
• 👥 <b>User Management</b> - View and manage users
• 📦 <b>Order Management</b> - View and manage orders
• 💰 <b>Deposit Management</b> - View and manage deposits
• 📊 <b>System Stats</b> - View system statistics
• 📅 <b>Subscription Management</b> - Manage subscriptions

<i>Select any option to continue or go back to the main menu.</i>
""",
            parse_mode='HTML',
            reply_markup=AdminSection.create_admin_menu()
        )
    
    @staticmethod
    def back_to_main_menu(bot, message):
        """Return to main menu"""
        chat_id = message.chat.id
        
        # Clear admin state
        if chat_id in admin_states:
            del admin_states[chat_id]
        
        # Clear pagination data
        if chat_id in pagination_data:
            del pagination_data[chat_id]
        
        # Return to main menu - this handler just removes admin keyboard
        # The actual main menu will be handled by the bot's main menu handler
        bot.send_message(
            chat_id, 
            "Returning to main menu...",
            reply_markup=ReplyKeyboardMarkup(resize_keyboard=True)
        )
    
    @staticmethod
    def back_to_admin(bot, message):
        """Return to admin dashboard"""
        AdminSection.handle_admin_dashboard(bot, message)


class UserManagement(AdminSection):
    """User management section of admin panel"""
    
    @staticmethod
    def show_user_management(bot, message):
        """Show user management options"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        # Set up user management menu
        user_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        user_menu.add(
            KeyboardButton('📋 List All Users'),
            KeyboardButton('🔍 Find User')
        )
        user_menu.add(
            KeyboardButton('➕ Add Balance'),
            KeyboardButton('⛔ Ban User')
        )
        user_menu.add(
            KeyboardButton('✅ Unban User'),
            KeyboardButton('📝 User Stats')
        )
        user_menu.add(KeyboardButton('🔙 Back to Admin'))
        
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👥 <b>USER MANAGEMENT</b> 👥  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Select a user management option:

• 📋 <b>List All Users</b> - View all registered users
• 🔍 <b>Find User</b> - Search for a specific user
• ➕ <b>Add Balance</b> - Add balance to a user account
• ⛔ <b>Ban User</b> - Ban a user from using the bot
• ✅ <b>Unban User</b> - Remove ban from a user
• 📝 <b>User Stats</b> - View detailed user statistics
""",
            parse_mode='HTML',
            reply_markup=user_menu
        )
    
    @staticmethod
    def list_all_users(bot, message):
        """List all users with pagination"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Count total users
            total_users = session.query(func.count(User.id)).scalar()
            
            if total_users == 0:
                bot.send_message(chat_id, "No users registered yet.")
                return
            
            # Initialize pagination for this chat
            pagination_data[chat_id] = {
                'type': 'users',
                'page': 1,
                'total_pages': (total_users + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            }
            
            # Fetch users for the first page
            users = session.query(User).order_by(User.id).limit(ITEMS_PER_PAGE).all()
            
            # Display users
            UserManagement._display_users_page(bot, chat_id, users, 1, pagination_data[chat_id]['total_pages'])
            
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error listing users. Please try again.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def _display_users_page(bot, chat_id, users, page, total_pages):
        """Display a page of users with pagination buttons"""
        if not users:
            bot.send_message(chat_id, "No users found.")
            return
        
        # Create message text
        message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>USER LIST</b> (Page {page}/{total_pages}) 📋  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
        
        for i, user in enumerate(users, 1):
            # Format subscription status
            sub_status = "✅ Active" if user.subscription_date and (datetime.utcnow() - user.subscription_date).days < 30 else "❌ Inactive"
            
            # Format user details
            message_text += f"""
👤 <b>User #{user.id}</b> - {'🚫 BANNED' if user.is_banned else '✅ ACTIVE'}
• Name: <b>{user.name}</b>
• Telegram ID: <code>{user.telegram_id}</code>
• Balance: <b>${user.balance:.2f}</b>
• Subscription: <b>{sub_status}</b>
• Registered: <b>{user.created_at.strftime('%Y-%m-%d')}</b>
"""
        
        # Create pagination keyboard
        keyboard = InlineKeyboardMarkup(row_width=5)
        buttons = []
        
        # First page button
        buttons.append(InlineKeyboardButton("⏮️", callback_data=f"users_page_1"))
        
        # Previous page button
        if page > 1:
            buttons.append(InlineKeyboardButton("◀️", callback_data=f"users_page_{page-1}"))
        else:
            buttons.append(InlineKeyboardButton("◀️", callback_data=f"users_page_1"))
        
        # Current page indicator
        buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data=f"users_page_current"))
        
        # Next page button
        if page < total_pages:
            buttons.append(InlineKeyboardButton("▶️", callback_data=f"users_page_{page+1}"))
        else:
            buttons.append(InlineKeyboardButton("▶️", callback_data=f"users_page_{total_pages}"))
        
        # Last page button
        buttons.append(InlineKeyboardButton("⏭️", callback_data=f"users_page_{total_pages}"))
        
        keyboard.add(*buttons)
        
        # Add user management buttons
        for user in users:
            keyboard.add(InlineKeyboardButton(
                f"Manage User #{user.id} ({user.name})",
                callback_data=f"manage_user_{user.id}"
            ))
        
        bot.send_message(
            chat_id,
            message_text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    
    @staticmethod
    def handle_users_pagination(bot, call):
        """Handle user list pagination"""
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
        
        # Extract page number from callback data
        if call.data == "users_page_current":
            bot.answer_callback_query(call.id, "Current page")
            return
            
        try:
            page = int(call.data.split('_')[-1])
            
            session = get_session()
            
            # Get total users count
            total_users = session.query(func.count(User.id)).scalar()
            total_pages = (total_users + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            
            # Update pagination data
            if chat_id in pagination_data:
                pagination_data[chat_id]['page'] = page
                pagination_data[chat_id]['total_pages'] = total_pages
            else:
                pagination_data[chat_id] = {
                    'type': 'users',
                    'page': page,
                    'total_pages': total_pages
                }
            
            # Ensure page is within bounds
            page = max(1, min(page, total_pages))
            
            # Fetch users for the requested page
            users = session.query(User).order_by(User.id).offset((page-1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()
            
            # Generate updated message text
            message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>USER LIST</b> (Page {page}/{total_pages}) 📋  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
            
            for i, user in enumerate(users, 1):
                # Format subscription status
                sub_status = "✅ Active" if user.subscription_date and (datetime.utcnow() - user.subscription_date).days < 30 else "❌ Inactive"
                
                # Format user details
                message_text += f"""
👤 <b>User #{user.id}</b> - {'🚫 BANNED' if user.is_banned else '✅ ACTIVE'}
• Name: <b>{user.name}</b>
• Telegram ID: <code>{user.telegram_id}</code>
• Balance: <b>${user.balance:.2f}</b>
• Subscription: <b>{sub_status}</b>
• Registered: <b>{user.created_at.strftime('%Y-%m-%d')}</b>
"""
            
            # Create updated pagination keyboard
            keyboard = InlineKeyboardMarkup(row_width=5)
            buttons = []
            
            # First page button
            buttons.append(InlineKeyboardButton("⏮️", callback_data=f"users_page_1"))
            
            # Previous page button
            if page > 1:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"users_page_{page-1}"))
            else:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"users_page_1"))
            
            # Current page indicator
            buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data=f"users_page_current"))
            
            # Next page button
            if page < total_pages:
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"users_page_{page+1}"))
            else:
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"users_page_{total_pages}"))
            
            # Last page button
            buttons.append(InlineKeyboardButton("⏭️", callback_data=f"users_page_{total_pages}"))
            
            keyboard.add(*buttons)
            
            # Add user management buttons
            for user in users:
                keyboard.add(InlineKeyboardButton(
                    f"Manage User #{user.id} ({user.name})",
                    callback_data=f"manage_user_{user.id}"
                ))
            
            # Update the message
            bot.edit_message_text(
                message_text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            bot.answer_callback_query(call.id, f"Page {page} of {total_pages}")
            
        except Exception as e:
            logger.error(f"Error handling user pagination: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error updating user list")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def find_user_prompt(bot, message):
        """Prompt admin to search for a user"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        # Update admin state
        admin_states[chat_id] = 'waiting_for_user_search'
        
        # Create cancel button
        cancel_markup = ReplyKeyboardMarkup(resize_keyboard=True)
        cancel_markup.add(KeyboardButton('🔙 Back to User Management'))
        
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>FIND USER</b> 🔍  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Enter a Telegram ID, name, or phone number to search for a user.

<i>• Telegram ID must be exact</i>
<i>• Name/phone can be partial</i>

Type your search query or click 'Back' to cancel.
""",
            parse_mode='HTML',
            reply_markup=cancel_markup
        )
    
    @staticmethod
    def search_user(bot, message):
        """Search for a user based on input"""
        chat_id = message.chat.id
        search_query = message.text.strip()
        
        # Return to user management if back button clicked
        if search_query == '🔙 Back to User Management':
            admin_states.pop(chat_id, None)
            UserManagement.show_user_management(bot, message)
            return
            
        session = None
        try:
            session = get_session()
            
            # Try to search by Telegram ID (exact match)
            try:
                telegram_id = int(search_query)
                user = session.query(User).filter_by(telegram_id=telegram_id).first()
                if user:
                    UserManagement._display_user_details(bot, chat_id, user)
                    # Clear admin state
                    admin_states.pop(chat_id, None)
                    return
            except ValueError:
                # Not a Telegram ID, continue to other search methods
                pass
            
            # Search by name (fuzzy)
            name_matches = session.query(User).filter(User.name.ilike(f'%{search_query}%')).all()
            
            # Search by phone (fuzzy)
            phone_matches = session.query(User).filter(User.phone.ilike(f'%{search_query}%')).all()
            
            # Combine results (without duplicates)
            all_matches = list(set(name_matches + phone_matches))
            
            if not all_matches:
                bot.send_message(
                    chat_id,
                    "No users found matching your query. Please try again with a different search term.",
                    reply_markup=UserManagement._get_back_markup()
                )
                return
                
            if len(all_matches) == 1:
                # Single match - show details
                UserManagement._display_user_details(bot, chat_id, all_matches[0])
                # Clear admin state
                admin_states.pop(chat_id, None)
            else:
                # Multiple matches - show list
                result_text = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔍 <b>SEARCH RESULTS</b> 🔍  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Multiple users found. Select one:</b>
"""
                
                # Create inline keyboard for selection
                keyboard = InlineKeyboardMarkup(row_width=1)
                
                for user in all_matches:
                    result_text += f"\n• <b>{user.name}</b> (ID: <code>{user.telegram_id}</code>)"
                    keyboard.add(InlineKeyboardButton(
                        f"{user.name} (ID: {user.telegram_id})",
                        callback_data=f"manage_user_{user.id}"
                    ))
                
                bot.send_message(
                    chat_id,
                    result_text,
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                
                # Clear admin state
                admin_states.pop(chat_id, None)
                
        except Exception as e:
            logger.error(f"Error searching user: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(
                chat_id,
                "Error searching for user. Please try again.",
                reply_markup=UserManagement._get_back_markup()
            )
        finally:
            safe_close_session(session)
    
    @staticmethod
    def _display_user_details(bot, chat_id, user):
        """Display detailed information about a user"""
        session = None
        try:
            session = get_session()
            
            # Get order stats
            order_count = session.query(func.count(Order.id)).filter_by(user_id=user.id).scalar()
            completed_orders = session.query(func.count(Order.id)).filter_by(
                user_id=user.id, status='Delivered').scalar()
            
            # Get deposit stats
            deposit_count = session.query(func.count(PendingDeposit.id)).filter_by(
                user_id=user.id, status='Approved').scalar()
            total_deposits = session.query(func.sum(PendingDeposit.amount)).filter_by(
                user_id=user.id, status='Approved').scalar() or 0
            
            # Calculate subscription status
            sub_status = "❌ Inactive"
            days_remaining = -1
            
            if user.subscription_date:
                days_passed = (datetime.utcnow() - user.subscription_date).days
                if days_passed < 30:
                    days_remaining = 30 - days_passed
                    sub_status = f"✅ Active ({days_remaining} days left)"
            
            # Format user details
            account_age = (datetime.utcnow() - user.created_at).days
            
            user_info = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   👤 <b>USER DETAILS</b> 👤  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Basic Information:</b>
• Name: <b>{user.name}</b>
• Telegram ID: <code>{user.telegram_id}</code>
• Phone: <b>{user.phone}</b>
• Email: <b>{user.email or 'N/A'}</b>
• Address: <b>{user.address}</b>
• Account Age: <b>{account_age} days</b>
• Status: <b>{'🚫 BANNED' if user.is_banned else '✅ ACTIVE'}</b>

<b>Financial Information:</b>
• Balance: <b>${user.balance:.2f}</b>
• Total Deposits: <b>${total_deposits:.2f}</b> ({deposit_count} deposits)
• Referral Points: <b>{user.referral_points}</b>

<b>Subscription:</b>
• Status: <b>{sub_status}</b>
• First Registered: <b>{user.created_at.strftime('%Y-%m-%d')}</b>

<b>Order Statistics:</b>
• Total Orders: <b>{order_count}</b>
• Completed Orders: <b>{completed_orders}</b>
"""
            
            # Create management keyboard
            keyboard = InlineKeyboardMarkup(row_width=2)
            
            # Add management buttons
            keyboard.add(
                InlineKeyboardButton("💰 Add Balance", callback_data=f"add_balance_{user.id}"),
                InlineKeyboardButton("📝 Edit Info", callback_data=f"edit_user_{user.id}")
            )
            
            if user.is_banned:
                keyboard.add(InlineKeyboardButton("✅ Unban User", callback_data=f"unban_user_{user.id}"))
            else:
                keyboard.add(InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_user_{user.id}"))
            
            keyboard.add(
                InlineKeyboardButton("📦 View Orders", callback_data=f"user_orders_{user.id}"),
                InlineKeyboardButton("💳 View Deposits", callback_data=f"user_deposits_{user.id}")
            )
            
            bot.send_message(
                chat_id,
                user_info,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error displaying user details: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error retrieving user details.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def handle_manage_user(bot, call):
        """Handle user management options for a specific user"""
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
            
        try:
            # Extract user ID from callback data
            user_id = int(call.data.split('_')[-1])
            action = call.data.split('_')[0]
            
            session = get_session()
            user = session.query(User).filter_by(id=user_id).first()
            
            if not user:
                bot.answer_callback_query(call.id, "User not found")
                return
                
            # Handle different actions
            if action == "manage":
                # Display user details
                UserManagement._display_user_details(bot, chat_id, user)
                bot.answer_callback_query(call.id, f"Managing user {user.name}")
                
            elif action == "ban":
                # Ban user
                user.is_banned = True
                session.commit()
                
                bot.answer_callback_query(call.id, f"User {user.name} has been banned")
                
                # Notify the user
                try:
                    bot.send_message(
                        user.telegram_id,
                        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚫 <b>ACCOUNT BANNED</b> 🚫  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your account has been banned by an administrator.

<i>Please contact support if you believe this is an error.</i>
""",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Error notifying user about ban: {e}")
                
                # Update admin view
                UserManagement._display_user_details(bot, chat_id, user)
                
            elif action == "unban":
                # Unban user
                user.is_banned = False
                session.commit()
                
                bot.answer_callback_query(call.id, f"User {user.name} has been unbanned")
                
                # Notify the user
                try:
                    bot.send_message(
                        user.telegram_id,
                        """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>ACCOUNT RESTORED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your account has been unbanned by an administrator.

<i>You may now use all features of the bot again.</i>
""",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Error notifying user about unban: {e}")
                
                # Update admin view
                UserManagement._display_user_details(bot, chat_id, user)
                
            elif action == "add":
                # Set up state for adding balance
                admin_states[chat_id] = {
                    'action': 'adding_balance',
                    'user_id': user_id
                }
                
                # Create cancel button
                cancel_markup = ReplyKeyboardMarkup(resize_keyboard=True)
                cancel_markup.add(KeyboardButton('🔙 Cancel'))
                
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>ADD BALANCE</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Adding balance for user: <b>{user.name}</b>
Current balance: <b>${user.balance:.2f}</b>

Enter the amount to add (in USD):
""",
                    parse_mode='HTML',
                    reply_markup=cancel_markup
                )
                
                bot.answer_callback_query(call.id, f"Enter amount to add for {user.name}")
                
        except Exception as e:
            logger.error(f"Error handling user management: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error processing request")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def process_balance_amount(bot, message):
        """Process the amount to add to user balance"""
        chat_id = message.chat.id
        
        if chat_id not in admin_states or admin_states[chat_id].get('action') != 'adding_balance':
            return
            
        if message.text == '🔙 Cancel':
            bot.send_message(chat_id, "Balance addition cancelled.")
            admin_states.pop(chat_id, None)
            return
            
        try:
            amount = float(message.text.strip())
            
            if amount <= 0:
                bot.send_message(chat_id, "Please enter a positive amount.")
                return
                
            user_id = admin_states[chat_id]['user_id']
            
            session = get_session()
            user = session.query(User).filter_by(id=user_id).first()
            
            if not user:
                bot.send_message(chat_id, "User not found. Operation cancelled.")
                admin_states.pop(chat_id, None)
                return
                
            # Store original balance
            original_balance = user.balance
            
            # Add balance
            user.balance += amount
            
            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                amount=amount,
                transaction_type="admin_addition",
                description=f"Balance added by administrator",
                status="completed"
            )
            session.add(transaction)
            
            session.commit()
            
            # Notify admin
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>BALANCE ADDED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Successfully added <b>${amount:.2f}</b> to {user.name}'s account.

• Previous balance: <b>${original_balance:.2f}</b>
• New balance: <b>${user.balance:.2f}</b>

<i>The user has been notified about this change.</i>
""",
                parse_mode='HTML',
                reply_markup=AdminSection.create_admin_menu()
            )
            
            # Notify user
            try:
                bot.send_message(
                    user.telegram_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>BALANCE UPDATED</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>${amount:.2f}</b> has been added to your account by an administrator.

• Previous balance: <b>${original_balance:.2f}</b>
• New balance: <b>${user.balance:.2f}</b>

<i>Thank you for using our service!</i>
""",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error notifying user about balance addition: {e}")
            
            # Clear admin state
            admin_states.pop(chat_id, None)
            
        except ValueError:
            bot.send_message(
                chat_id,
                "Invalid amount. Please enter a numeric value (e.g., 10.50)."
            )
        except Exception as e:
            logger.error(f"Error adding balance: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(
                chat_id, 
                "Error adding balance. Operation cancelled.",
                reply_markup=AdminSection.create_admin_menu()
            )
            # Clear admin state
            admin_states.pop(chat_id, None)
        finally:
            safe_close_session(session)
    
    @staticmethod
    def _get_back_markup():
        """Create a keyboard with back button"""
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(KeyboardButton('🔙 Back to User Management'))
        return markup


class OrderManagement(AdminSection):
    """Order management section of admin panel"""
    
    @staticmethod
    def show_order_management(bot, message):
        """Show order management options"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        # Set up order management menu
        order_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        order_menu.add(
            KeyboardButton('📋 List All Orders'),
            KeyboardButton('🔍 Find Order')
        )
        order_menu.add(
            KeyboardButton('📦 Pending Orders'),
            KeyboardButton('✅ Completed Orders')
        )
        order_menu.add(KeyboardButton('🔙 Back to Admin'))
        
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📦 <b>ORDER MANAGEMENT</b> 📦  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Select an order management option:

• 📋 <b>List All Orders</b> - View all orders
• 🔍 <b>Find Order</b> - Search for a specific order
• 📦 <b>Pending Orders</b> - View orders waiting for processing
• ✅ <b>Completed Orders</b> - View delivered orders
""",
            parse_mode='HTML',
            reply_markup=order_menu
        )
    
    @staticmethod
    def list_all_orders(bot, message):
        """List all orders with pagination"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Count total orders
            total_orders = session.query(func.count(Order.id)).scalar()
            
            if total_orders == 0:
                bot.send_message(chat_id, "No orders in the system yet.")
                return
            
            # Initialize pagination for this chat
            pagination_data[chat_id] = {
                'type': 'orders',
                'page': 1,
                'total_pages': (total_orders + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            }
            
            # Fetch orders for the first page
            orders = session.query(Order).order_by(desc(Order.created_at)).limit(ITEMS_PER_PAGE).all()
            
            # Display orders
            OrderManagement._display_orders_page(bot, chat_id, orders, 1, pagination_data[chat_id]['total_pages'])
            
        except Exception as e:
            logger.error(f"Error listing orders: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error listing orders. Please try again.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def _display_orders_page(bot, chat_id, orders, page, total_pages):
        """Display a page of orders with pagination buttons"""
        if not orders:
            bot.send_message(chat_id, "No orders found.")
            return
        
        # Create message text
        message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>ORDER LIST</b> (Page {page}/{total_pages}) 📋  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
        
        session = get_session()
        
        try:
            for i, order in enumerate(orders, 1):
                # Get user information
                user = session.query(User).filter_by(id=order.user_id).first()
                username = user.name if user else "Unknown User"
                
                # Format order status
                status_emoji = "✅" if order.status == "Delivered" else "🕒" if order.status == "Processing" else "📦" if order.status == "Shipped" else "❓"
                
                # Format order details
                message_text += f"""
{status_emoji} <b>Order #{order.order_number}</b> ({order.status})
• User: <b>{username}</b>
• Product: <b>{order.product_name[:30]}...</b>
• Amount: <b>${order.amount:.2f}</b>
• Date: <b>{order.created_at.strftime('%Y-%m-%d')}</b>
"""
                if order.tracking_number:
                    message_text += f"• Tracking: <code>{order.tracking_number}</code>\n"
            
            # Create pagination keyboard
            keyboard = InlineKeyboardMarkup(row_width=5)
            buttons = []
            
            # First page button
            buttons.append(InlineKeyboardButton("⏮️", callback_data=f"orders_page_1"))
            
            # Previous page button
            if page > 1:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"orders_page_{page-1}"))
            else:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"orders_page_1"))
            
            # Current page indicator
            buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data=f"orders_page_current"))
            
            # Next page button
            if page < total_pages:
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"orders_page_{page+1}"))
            else:
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"orders_page_{total_pages}"))
            
            # Last page button
            buttons.append(InlineKeyboardButton("⏭️", callback_data=f"orders_page_{total_pages}"))
            
            keyboard.add(*buttons)
            
            # Add order management buttons
            for order in orders:
                keyboard.add(InlineKeyboardButton(
                    f"Manage Order #{order.order_number}",
                    callback_data=f"manage_order_{order.id}"
                ))
            
            bot.send_message(
                chat_id,
                message_text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Error displaying orders: {e}")
            bot.send_message(chat_id, "Error displaying orders.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def handle_orders_pagination(bot, call):
        """Handle order list pagination"""
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
        
        # Extract page number from callback data
        if call.data == "orders_page_current":
            bot.answer_callback_query(call.id, "Current page")
            return
            
        try:
            page = int(call.data.split('_')[-1])
            
            session = get_session()
            
            # Get total orders count
            total_orders = session.query(func.count(Order.id)).scalar()
            total_pages = (total_orders + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
            
            # Update pagination data
            if chat_id in pagination_data:
                pagination_data[chat_id]['page'] = page
                pagination_data[chat_id]['total_pages'] = total_pages
            else:
                pagination_data[chat_id] = {
                    'type': 'orders',
                    'page': page,
                    'total_pages': total_pages
                }
            
            # Ensure page is within bounds
            page = max(1, min(page, total_pages))
            
            # Fetch orders for the requested page
            orders = session.query(Order).order_by(desc(Order.created_at)).offset((page-1) * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE).all()
            
            # Generate updated message text
            message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>ORDER LIST</b> (Page {page}/{total_pages}) 📋  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
            
            for i, order in enumerate(orders, 1):
                # Get user information
                user = session.query(User).filter_by(id=order.user_id).first()
                username = user.name if user else "Unknown User"
                
                # Format order status
                status_emoji = "✅" if order.status == "Delivered" else "🕒" if order.status == "Processing" else "📦" if order.status == "Shipped" else "❓"
                
                # Format order details
                message_text += f"""
{status_emoji} <b>Order #{order.order_number}</b> ({order.status})
• User: <b>{username}</b>
• Product: <b>{order.product_name[:30]}...</b>
• Amount: <b>${order.amount:.2f}</b>
• Date: <b>{order.created_at.strftime('%Y-%m-%d')}</b>
"""
                if order.tracking_number:
                    message_text += f"• Tracking: <code>{order.tracking_number}</code>\n"
            
            # Create updated pagination keyboard
            keyboard = InlineKeyboardMarkup(row_width=5)
            buttons = []
            
            # First page button
            buttons.append(InlineKeyboardButton("⏮️", callback_data=f"orders_page_1"))
            
            # Previous page button
            if page > 1:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"orders_page_{page-1}"))
            else:
                buttons.append(InlineKeyboardButton("◀️", callback_data=f"orders_page_1"))
            
            # Current page indicator
            buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data=f"orders_page_current"))
            
            # Next page button
            if page < total_pages:
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"orders_page_{page+1}"))
            else:
                buttons.append(InlineKeyboardButton("▶️", callback_data=f"orders_page_{total_pages}"))
            
            # Last page button
            buttons.append(InlineKeyboardButton("⏭️", callback_data=f"orders_page_{total_pages}"))
            
            keyboard.add(*buttons)
            
            # Add order management buttons
            for order in orders:
                keyboard.add(InlineKeyboardButton(
                    f"Manage Order #{order.order_number}",
                    callback_data=f"manage_order_{order.id}"
                ))
            
            # Update the message
            bot.edit_message_text(
                message_text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            
            bot.answer_callback_query(call.id, f"Page {page} of {total_pages}")
            
        except Exception as e:
            logger.error(f"Error handling order pagination: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error updating order list")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def handle_manage_order(bot, call):
        """Handle order management options for a specific order"""
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
            
        try:
            # Extract order ID from callback data
            order_id = int(call.data.split('_')[-1])
            
            session = get_session()
            order = session.query(Order).filter_by(id=order_id).first()
            
            if not order:
                bot.answer_callback_query(call.id, "Order not found")
                return
                
            user = session.query(User).filter_by(id=order.user_id).first()
            username = user.name if user else "Unknown User"
            
            # Format tracking info if available
            tracking_info = ""
            tracking_link = ""
            if order.tracking_number:
                clean_tracking = order.tracking_number.strip().replace(" ", "").replace("+", "%2B")
                tracking_link = f"https://global.cainiao.com/detail.htm?mailNo={clean_tracking}&lang=en"
                tracking_info = f"""
• Tracking Number: <code>{order.tracking_number}</code>
• <a href="{tracking_link}">Track Package</a>
• <a href="https://aliexpress.com/trackOrder.htm">Track on AliExpress</a>
"""
                
            # Create message with order details
            order_info = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📦 <b>ORDER DETAILS</b> 📦  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Order #{order.order_number}</b>

<b>Basic Information:</b>
• Status: <b>{order.status}</b>
• User: <b>{username}</b> (ID: <code>{user.telegram_id if user else 'Unknown'}</code>)
• Created: <b>{order.created_at.strftime('%Y-%m-%d %H:%M')}</b>
• Updated: <b>{order.updated_at.strftime('%Y-%m-%d %H:%M')}</b>

<b>Product Information:</b>
• Name: <b>{order.product_name}</b>
• Link: <a href="{order.product_link}">View Product</a>
• Amount: <b>${order.amount:.2f}</b>

<b>Shipping Information:</b>
• AliExpress Order ID: <code>{order.order_id or 'Not set'}</code>
{tracking_info}
"""
            
            # Create management keyboard
            keyboard = InlineKeyboardMarkup(row_width=2)
            
            # Add management buttons
            keyboard.add(
                InlineKeyboardButton("✏️ Update Order", callback_data=f"update_order_{order.id}"),
                InlineKeyboardButton("🔄 Change Status", callback_data=f"change_status_{order.id}")
            )
            
            if not order.tracking_number:
                keyboard.add(InlineKeyboardButton("🚚 Add Tracking", callback_data=f"add_tracking_{order.id}"))
            else:
                keyboard.add(InlineKeyboardButton("🚚 Update Tracking", callback_data=f"add_tracking_{order.id}"))
                
            # Contact user button
            if user:
                keyboard.add(InlineKeyboardButton("👤 View User", callback_data=f"manage_user_{user.id}"))
            
            bot.send_message(
                chat_id,
                order_info,
                parse_mode='HTML',
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
            bot.answer_callback_query(call.id, f"Managing Order #{order.order_number}")
            
        except Exception as e:
            logger.error(f"Error handling order management: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error processing request")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def handle_update_order(bot, call):
        """Handle order update request"""
        chat_id = call.message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
            
        try:
            # Extract order ID from callback data
            order_id = int(call.data.split('_')[-1])
            action = call.data.split('_')[0]
            
            session = get_session()
            order = session.query(Order).filter_by(id=order_id).first()
            
            if not order:
                bot.answer_callback_query(call.id, "Order not found")
                return
                
            # Set up state for updating order
            admin_states[chat_id] = {
                'action': action,
                'order_id': order_id
            }
            
            # Create cancel button
            cancel_markup = ReplyKeyboardMarkup(resize_keyboard=True)
            cancel_markup.add(KeyboardButton('🔙 Cancel'))
            
            if action == "update":
                # Updating entire order
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✏️ <b>UPDATE ORDER</b> ✏️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Updating Order #{order.order_number}

Please enter the order details in the following format:
<code>aliexpress_id|tracking_number|price</code>

Example: <code>92834729374|LX123456789CN|12.50</code>

• If you don't have a tracking number, use empty space: <code>92834729374||12.50</code>
• If you don't want to change the price: <code>92834729374|LX123456789CN|{order.amount:.2f}</code>

Type 'cancel' to cancel.
""",
                    parse_mode='HTML',
                    reply_markup=cancel_markup
                )
            elif action == "add":
                # Adding/updating tracking
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚚 <b>UPDATE TRACKING</b> 🚚  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Adding tracking for Order #{order.order_number}

Please enter the tracking number:

Current: {order.tracking_number or 'None'}

Type 'cancel' to cancel.
""",
                    parse_mode='HTML',
                    reply_markup=cancel_markup
                )
            elif action == "change":
                # Changing status
                status_markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
                status_markup.add(
                    KeyboardButton('🕒 Processing'),
                    KeyboardButton('📦 Shipped')
                )
                status_markup.add(
                    KeyboardButton('✅ Delivered'),
                    KeyboardButton('❌ Cancelled')
                )
                status_markup.add(KeyboardButton('🔙 Cancel'))
                
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔄 <b>CHANGE STATUS</b> 🔄  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Changing status for Order #{order.order_number}

Current status: <b>{order.status}</b>

Select a new status:
""",
                    parse_mode='HTML',
                    reply_markup=status_markup
                )
            
            bot.answer_callback_query(call.id, f"Updating Order #{order.order_number}")
            
        except Exception as e:
            logger.error(f"Error setting up order update: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error processing request")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def process_order_update(bot, message):
        """Process order update from admin"""
        chat_id = message.chat.id
        update_text = message.text.strip()
        
        if chat_id not in admin_states:
            return
            
        state = admin_states[chat_id]
        
        if 'action' not in state or 'order_id' not in state:
            return
            
        action = state['action']
        order_id = state['order_id']
        
        # Handle cancel
        if update_text.lower() == 'cancel' or update_text == '🔙 Cancel':
            bot.send_message(chat_id, "Update cancelled.")
            admin_states.pop(chat_id, None)
            OrderManagement.show_order_management(bot, message)
            return
            
        session = None
        try:
            session = get_session()
            order = session.query(Order).filter_by(id=order_id).first()
            
            if not order:
                bot.send_message(chat_id, "Order not found. Operation cancelled.")
                admin_states.pop(chat_id, None)
                return
                
            user = session.query(User).filter_by(id=order.user_id).first()
            
            if action == "update":
                # Process full order update
                try:
                    order_details = update_text.strip().split('|')
                    if len(order_details) != 3:
                        raise ValueError("Invalid format")
                    
                    aliexpress_id, tracking, price = order_details
                    price = float(price) if price.strip() else order.amount
                    
                except (ValueError, IndexError):
                    bot.reply_to(message, "Invalid format. Please use: orderid|tracking|price")
                    return
                
                # Store original values
                original_amount = order.amount
                original_status = order.status
                
                # Update order details
                order.order_id = aliexpress_id
                order.tracking_number = tracking.strip() if tracking.strip() else None
                order.amount = price
                order.status = "Shipped" if tracking.strip() else "Processing"
                order.updated_at = datetime.utcnow()
                
                session.commit()
                
                # Notify user if needed
                if user and (tracking.strip() or original_status != order.status):
                    tracking_info = ""
                    if tracking.strip():
                        clean_tracking = tracking.strip().replace(" ", "").replace("+", "%2B")      
                        parcels_app_link = f"https://global.cainiao.com/detail.htm?mailNo={clean_tracking}&lang=en"
                        tracking_info = f"""
<b>📬 TRACKING INFORMATION:</b>
• Number: <code>{tracking.strip()}</code>
• Carrier: <b>Standard AliExpress Shipping</b>
• <a href="{parcels_app_link}">Track Package</a>
• <a href="https://aliexpress.com/trackOrder.htm">Track on AliExpress</a>
"""
                    
                    try:
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🎉 <b>ORDER UPDATE</b> 🎉  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your order <b>#{order.order_number}</b> has been updated!

<b>📋 ORDER DETAILS:</b>
• Status: <b>{order.status}</b>
• AliExpress ID: <code>{aliexpress_id}</code>
• Amount: <b>${price:.2f}</b>
{tracking_info}

<i>Need help? Contact our support team!</i>
""",
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logger.error(f"Error notifying user about order update: {e}")
                
                # Confirm to admin
                bot.reply_to(
                    message,
                    f"""
✅ Order updated successfully:
• Order #{order.order_number}
• ID: {aliexpress_id}
• Tracking: {tracking.strip() if tracking.strip() else "None"}
• Amount: ${price:.2f} (was: ${original_amount:.2f})
• Status: {order.status} (was: {original_status})

User has been notified of changes.
""",
                    parse_mode='HTML',
                    reply_markup=AdminSection.create_admin_menu()
                )
                
            elif action == "add":
                # Update tracking number only
                tracking = update_text.strip()
                original_status = order.status
                
                order.tracking_number = tracking
                order.status = "Shipped" if tracking else original_status
                order.updated_at = datetime.utcnow()
                
                session.commit()
                
                # Notify user
                if user:
                    clean_tracking = tracking.replace(" ", "").replace("+", "%2B")      
                    parcels_app_link = f"https://global.cainiao.com/detail.htm?mailNo={clean_tracking}&lang=en"
                    
                    try:
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🚚 <b>TRACKING UPDATED</b> 🚚  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your order <b>#{order.order_number}</b> has been shipped!

<b>📬 TRACKING INFORMATION:</b>
• Number: <code>{tracking}</code>
• Carrier: <b>Standard AliExpress Shipping</b>
• <a href="{parcels_app_link}">Track Package</a>
• <a href="https://aliexpress.com/trackOrder.htm">Track on AliExpress</a>

<i>Need help? Contact our support team!</i>
""",
                            parse_mode='HTML',
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logger.error(f"Error notifying user about tracking update: {e}")
                
                # Confirm to admin
                bot.reply_to(
                    message,
                    f"""
✅ Tracking updated successfully:
• Order #{order.order_number}
• Tracking: {tracking}
• Status: {order.status} (was: {original_status})

User has been notified of the update.
""",
                    parse_mode='HTML',
                    reply_markup=AdminSection.create_admin_menu()
                )
                
            elif action == "change":
                # Update status only
                status_map = {
                    '🕒 Processing': 'Processing',
                    '📦 Shipped': 'Shipped',
                    '✅ Delivered': 'Delivered',
                    '❌ Cancelled': 'Cancelled'
                }
                
                status = status_map.get(update_text, update_text)
                original_status = order.status
                
                order.status = status
                order.updated_at = datetime.utcnow()
                
                session.commit()
                
                # Notify user
                if user:
                    try:
                        bot.send_message(
                            user.telegram_id,
                            f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🔄 <b>STATUS UPDATED</b> 🔄  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your order <b>#{order.order_number}</b> status has been updated.

• Previous status: <b>{original_status}</b>
• New status: <b>{status}</b>

<i>Need help? Contact our support team!</i>
""",
                            parse_mode='HTML'
                        )
                    except Exception as e:
                        logger.error(f"Error notifying user about status update: {e}")
                
                # Confirm to admin
                bot.reply_to(
                    message,
                    f"""
✅ Status updated successfully:
• Order #{order.order_number}
• Previous status: {original_status}
• New status: {status}

User has been notified of the status change.
""",
                    parse_mode='HTML',
                    reply_markup=AdminSection.create_admin_menu()
                )
            
            # Clear admin state
            admin_states.pop(chat_id, None)
            
        except Exception as e:
            logger.error(f"Error updating order: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(
                chat_id, 
                "Error updating order. Operation cancelled.",
                reply_markup=AdminSection.create_admin_menu()
            )
            # Clear admin state
            admin_states.pop(chat_id, None)
        finally:
            safe_close_session(session)


class DepositManagement(AdminSection):
    """Deposit management section of admin panel"""
    
    @staticmethod
    def show_deposit_management(bot, message):
        """Show deposit management options"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        # Set up deposit management menu
        deposit_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        deposit_menu.add(
            KeyboardButton('📋 List Pending Deposits'),
            KeyboardButton('🕒 Recent Deposits')
        )
        deposit_menu.add(
            KeyboardButton('➕ Add Balance'),
            KeyboardButton('🔙 Back to Admin')
        )
        
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>DEPOSIT MANAGEMENT</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Select a deposit management option:

• 📋 <b>Pending Deposits</b> - Review deposits awaiting approval
• 🕒 <b>Recent Deposits</b> - View recently processed deposits
• ➕ <b>Add Balance</b> - Add balance to a user's account
""",
            parse_mode='HTML',
            reply_markup=deposit_menu
        )
    
    @staticmethod
    def list_pending_deposits(bot, message):
        """List pending deposits for approval"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Get pending deposits
            pending_deposits = session.query(PendingDeposit, User).join(User).filter(
                PendingDeposit.status == 'Pending'
            ).order_by(PendingDeposit.created_at).all()
            
            if not pending_deposits:
                bot.send_message(
                    chat_id,
                    """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>PENDING DEPOSITS</b> 📋  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

There are no pending deposits at this time.
""",
                    parse_mode='HTML'
                )
                return
            
            bot.send_message(
                chat_id,
                f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📋 <b>PENDING DEPOSITS</b> 📋  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

There are <b>{len(pending_deposits)}</b> deposits awaiting approval.
Each deposit will be shown individually.
""",
                parse_mode='HTML'
            )
            
            # Display each pending deposit
            for deposit, user in pending_deposits:
                # Create approval keyboard
                keyboard = InlineKeyboardMarkup(row_width=2)
                keyboard.add(
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_deposit_{deposit.id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_deposit_{deposit.id}")
                )
                
                # Calculate when deposit was made
                time_diff = datetime.utcnow() - deposit.created_at
                if time_diff.days > 0:
                    time_ago = f"{time_diff.days} days ago"
                elif time_diff.seconds >= 3600:
                    time_ago = f"{time_diff.seconds // 3600} hours ago"
                else:
                    time_ago = f"{time_diff.seconds // 60} minutes ago"
                
                # Send deposit details with screenshot
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   💰 <b>DEPOSIT #{deposit.id}</b> 💰  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Deposit Details:</b>
• User: <b>{user.name}</b> (ID: <code>{user.telegram_id}</code>)
• Amount: <b>${deposit.amount:.2f}</b>
• Current balance: <b>${user.balance:.2f}</b>
• Reference: <code>{deposit.reference or 'None'}</code>
• Submitted: <b>{time_ago}</b>

<i>Payment screenshot is attached above.</i>
<i>Review the image and click Approve or Reject.</i>
""",
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                
                # Send screenshot if available
                if deposit.screenshot_file_id:
                    try:
                        bot.send_photo(
                            chat_id,
                            deposit.screenshot_file_id,
                            caption=f"💳 Payment proof for deposit #{deposit.id} - ${deposit.amount:.2f}"
                        )
                    except Exception as e:
                        logger.error(f"Error sending screenshot: {e}")
                        bot.send_message(
                            chat_id,
                            "⚠️ Error retrieving screenshot. Screenshot may be unavailable."
                        )
            
        except Exception as e:
            logger.error(f"Error listing pending deposits: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error listing pending deposits. Please try again.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def handle_deposit_approval(bot, call):
        """Handle deposit approval/rejection"""
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
            
        try:
            parts = call.data.split('_deposit_')
            action = parts[0]  # approve or reject
            deposit_id = int(parts[1])
            
            session = get_session()
            deposit_info = session.query(PendingDeposit, User).join(User).filter(
                PendingDeposit.id == deposit_id
            ).first()
            
            if not deposit_info:
                bot.answer_callback_query(call.id, "Deposit not found or already processed")
                bot.edit_message_text(
                    "This deposit has already been processed.",
                    chat_id=chat_id,
                    message_id=message_id
                )
                return
            
            deposit, user = deposit_info
            
            if action == 'approve':
                # Add amount to user balance
                user.balance += deposit.amount
                
                # Handle subscription if needed
                now = datetime.utcnow()
                subscription_deducted = False
                subscription_renewal_msg = ""
                
                if not user.subscription_date or (now - user.subscription_date).days >= 30:
                    if deposit.amount >= 1.0:
                        amount_after_sub = deposit.amount - 1.0
                        user.balance = user.balance - deposit.amount + amount_after_sub
                        user.subscription_date = now
                        subscription_deducted = True
                        subscription_renewal_msg = f"\n📅 Subscription renewed until {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"
                
                deposit.status = 'Approved'
                deposit.updated_at = datetime.utcnow()
                deposit.balance_updated = True
                session.commit()
                
                # Notify user
                try:
                    bot.send_message(
                        user.telegram_id,
                        f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>DEPOSIT APPROVED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>Amount:</b> ${deposit.amount:.2f}
<b>New Balance:</b> ${user.balance:.2f}
{subscription_renewal_msg}

<i>Thank you for using our service!</i>
""",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Error notifying user about deposit approval: {e}")
                
                # Update admin message
                bot.edit_message_text(
                    f"""
<b>Deposit #{deposit.id}</b> - ✅ APPROVED

👤 User: {user.name}
💰 Amount: ${deposit.amount:.2f}
💳 New Balance: ${user.balance:.2f}
⏰ Time: {datetime.now().strftime("%Y-%m-%d %H:%M")}

<i>User has been notified.</i>
""",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
                
                bot.answer_callback_query(call.id, f"Deposit of ${deposit.amount:.2f} approved")
                
            else:  # reject
                deposit.status = 'Rejected'
                deposit.updated_at = datetime.utcnow()
                session.commit()
                
                # Notify user
                try:
                    bot.send_message(
                        user.telegram_id,
                        f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ❌ <b>DEPOSIT REJECTED</b> ❌  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your deposit of ${deposit.amount:.2f} was rejected.
Please try again with clear payment proof.

<i>Contact support if needed.</i>
""",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Error notifying user about deposit rejection: {e}")
                
                # Update admin message
                bot.edit_message_text(
                    f"""
<b>Deposit #{deposit.id}</b> - ❌ REJECTED

👤 User: {user.name}
💰 Amount: ${deposit.amount:.2f}
⏰ Time: {datetime.now().strftime("%Y-%m-%d %H:%M")}

<i>User has been notified.</i>
""",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
                
                bot.answer_callback_query(call.id, f"Deposit of ${deposit.amount:.2f} rejected")
                
        except Exception as e:
            logger.error(f"Error handling deposit approval: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error processing deposit")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def show_recent_deposits(bot, message):
        """Show recent deposits"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Get recent deposits (approved or rejected)
            recent_deposits = session.query(PendingDeposit, User).join(User).filter(
                PendingDeposit.status.in_(['Approved', 'Rejected'])
            ).order_by(desc(PendingDeposit.updated_at)).limit(10).all()
            
            if not recent_deposits:
                bot.send_message(
                    chat_id,
                    """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🕒 <b>RECENT DEPOSITS</b> 🕒  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

There are no recent deposits to display.
""",
                    parse_mode='HTML'
                )
                return
            
            # Create message with recent deposits
            message_text = """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🕒 <b>RECENT DEPOSITS</b> 🕒  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

"""
            
            for deposit, user in recent_deposits:
                # Format time ago
                time_diff = datetime.utcnow() - deposit.updated_at
                if time_diff.days > 0:
                    time_ago = f"{time_diff.days} days ago"
                elif time_diff.seconds >= 3600:
                    time_ago = f"{time_diff.seconds // 3600} hours ago"
                else:
                    time_ago = f"{time_diff.seconds // 60} minutes ago"
                
                # Format deposit status
                status_emoji = "✅" if deposit.status == "Approved" else "❌"
                
                message_text += f"""
{status_emoji} <b>Deposit #{deposit.id}</b> ({deposit.status})
• User: <b>{user.name}</b>
• Amount: <b>${deposit.amount:.2f}</b>
• Processed: <b>{time_ago}</b>

"""
            
            bot.send_message(
                chat_id,
                message_text,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error showing recent deposits: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error retrieving recent deposits. Please try again.")
        finally:
            safe_close_session(session)


class SubscriptionManagement(AdminSection):
    """Subscription management section of admin panel"""
    
    @staticmethod
    def show_subscription_management(bot, message):
        """Show subscription management options"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        # Set up subscription management menu
        subscription_menu = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        subscription_menu.add(
            KeyboardButton('📊 Subscription Stats'),
            KeyboardButton('🕒 Expiring Soon')
        )
        subscription_menu.add(
            KeyboardButton('✅ Renew Subscription'),
            KeyboardButton('🔙 Back to Admin')
        )
        
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📅 <b>SUBSCRIPTION MANAGEMENT</b> 📅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Select a subscription management option:

• 📊 <b>Subscription Stats</b> - View overall subscription statistics
• 🕒 <b>Expiring Soon</b> - View subscriptions expiring in the next 7 days
• ✅ <b>Renew Subscription</b> - Manually renew a user's subscription
""",
            parse_mode='HTML',
            reply_markup=subscription_menu
        )
    
    @staticmethod
    def show_subscription_stats(bot, message):
        """Show subscription statistics"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Get total users count
            total_users = session.query(func.count(User.id)).scalar()
            
            # Get active subscription count
            now = datetime.utcnow()
            active_subs = session.query(func.count(User.id)).filter(
                User.subscription_date.isnot(None),
                (now - User.subscription_date) < timedelta(days=30)
            ).scalar()
            
            # Get users with expiring subscriptions (within 7 days)
            expiring_soon = session.query(func.count(User.id)).filter(
                User.subscription_date.isnot(None),
                (now - User.subscription_date) >= timedelta(days=23),
                (now - User.subscription_date) < timedelta(days=30)
            ).scalar()
            
            # Get expired subscriptions
            expired_subs = session.query(func.count(User.id)).filter(
                User.subscription_date.isnot(None),
                (now - User.subscription_date) >= timedelta(days=30)
            ).scalar()
            
            # Get users with no subscription
            no_sub = session.query(func.count(User.id)).filter(
                User.subscription_date.is_(None)
            ).scalar()
            
            # Calculate monthly revenue (30 days)
            month_start = now - timedelta(days=30)
            monthly_revenue = session.query(func.sum(PendingDeposit.amount)).filter(
                PendingDeposit.status == 'Approved',
                PendingDeposit.updated_at >= month_start
            ).scalar() or 0
            
            # Create message with stats
            message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>SUBSCRIPTION STATISTICS</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>User Subscription Status:</b>
• Total Users: <b>{total_users}</b>
• Active Subscriptions: <b>{active_subs}</b> ({round(active_subs/total_users*100 if total_users else 0)}%)
• Expiring within 7 days: <b>{expiring_soon}</b>
• Expired Subscriptions: <b>{expired_subs}</b>
• No Subscription: <b>{no_sub}</b>

<b>Revenue:</b>
• Monthly Revenue (30 days): <b>${monthly_revenue:.2f}</b>
• Subscription Revenue: <b>${active_subs * 1.0:.2f}</b>
"""
            
            bot.send_message(
                chat_id,
                message_text,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error showing subscription stats: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error retrieving subscription statistics. Please try again.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def show_expiring_subscriptions(bot, message):
        """Show subscriptions expiring soon"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Get users with expiring subscriptions (within 7 days)
            now = datetime.utcnow()
            expiring_users = session.query(User).filter(
                User.subscription_date.isnot(None),
                (now - User.subscription_date) >= timedelta(days=23),
                (now - User.subscription_date) < timedelta(days=30)
            ).order_by(User.subscription_date).all()
            
            if not expiring_users:
                bot.send_message(
                    chat_id,
                    """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🕒 <b>EXPIRING SUBSCRIPTIONS</b> 🕒  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

There are no subscriptions expiring in the next 7 days.
""",
                    parse_mode='HTML'
                )
                return
            
            # Create message with expiring subscriptions
            message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   🕒 <b>EXPIRING SUBSCRIPTIONS</b> 🕒  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>{len(expiring_users)}</b> subscriptions are expiring in the next 7 days:
"""
            
            keyboard = InlineKeyboardMarkup(row_width=1)
            
            for user in expiring_users:
                # Calculate days remaining
                days_passed = (now - user.subscription_date).days
                days_remaining = 30 - days_passed
                
                message_text += f"""
• <b>{user.name}</b> (ID: <code>{user.telegram_id}</code>)
  Expires in <b>{days_remaining} days</b> ({user.subscription_date.strftime('%Y-%m-%d')})
  Balance: <b>${user.balance:.2f}</b>
"""
                
                keyboard.add(InlineKeyboardButton(
                    f"Renew {user.name}'s Subscription",
                    callback_data=f"renew_sub_{user.id}"
                ))
            
            bot.send_message(
                chat_id,
                message_text,
                parse_mode='HTML',
                reply_markup=keyboard
            )
            
        except Exception as e:
            logger.error(f"Error showing expiring subscriptions: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error retrieving expiring subscriptions. Please try again.")
        finally:
            safe_close_session(session)
    
    @staticmethod
    def show_renew_subscription(bot, message):
        """Show renew subscription prompt"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        # Update admin state
        admin_states[chat_id] = 'waiting_for_subscription_user_id'
        
        # Create cancel button
        cancel_markup = ReplyKeyboardMarkup(resize_keyboard=True)
        cancel_markup.add(KeyboardButton('🔙 Back to Subscription Management'))
        
        bot.send_message(
            chat_id,
            """
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>RENEW SUBSCRIPTION</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Enter the user's Telegram ID to renew their subscription:

<i>The subscription fee ($1.00) will be deducted from the user's balance.</i>
<i>If the user doesn't have sufficient balance, you'll be prompted to add balance.</i>
""",
            parse_mode='HTML',
            reply_markup=cancel_markup
        )
    
    @staticmethod
    def process_subscription_user_id(bot, message):
        """Process the user ID for renewing subscription"""
        chat_id = message.chat.id
        user_input = message.text.strip()
        
        # Handle back button
        if user_input == '🔙 Back to Subscription Management':
            admin_states.pop(chat_id, None)
            SubscriptionManagement.show_subscription_management(bot, message)
            return
        
        try:
            telegram_id = int(user_input)
            
            session = get_session()
            user = session.query(User).filter_by(telegram_id=telegram_id).first()
            
            if not user:
                bot.send_message(
                    chat_id,
                    "User not found. Please enter a valid Telegram ID.",
                    reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                        KeyboardButton('🔙 Back to Subscription Management')
                    )
                )
                return
            
            # Check if user has enough balance
            if user.balance < 1.0:
                # Not enough balance - offer to add balance
                keyboard = InlineKeyboardMarkup(row_width=2)
                keyboard.add(
                    InlineKeyboardButton("➕ Add Balance", callback_data=f"add_balance_{user.id}"),
                    InlineKeyboardButton("🔙 Cancel", callback_data="cancel_sub_renewal")
                )
                
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ⚠️ <b>INSUFFICIENT BALANCE</b> ⚠️  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

User <b>{user.name}</b> doesn't have sufficient balance.

• Current Balance: <b>${user.balance:.2f}</b>
• Required: <b>$1.00</b>
• Shortfall: <b>${max(0, 1.0 - user.balance):.2f}</b>

Would you like to add balance to this user's account?
""",
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                
                # Update admin state
                admin_states[chat_id] = {
                    'action': 'renewing_subscription',
                    'user_id': user.id
                }
                
            else:
                # Has enough balance - confirm renewal
                keyboard = InlineKeyboardMarkup(row_width=2)
                keyboard.add(
                    InlineKeyboardButton("✅ Confirm Renewal", callback_data=f"confirm_renew_{user.id}"),
                    InlineKeyboardButton("🔙 Cancel", callback_data="cancel_sub_renewal")
                )
                
                # Calculate new expiry date
                now = datetime.utcnow()
                if user.subscription_date and (now - user.subscription_date).days < 30:
                    # Subscription is still active - extend from current expiry
                    days_passed = (now - user.subscription_date).days
                    days_remaining = 30 - days_passed
                    new_expiry = user.subscription_date + timedelta(days=30)
                    current_status = f"Active (expires in {days_remaining} days)"
                else:
                    # Subscription is expired or never activated
                    new_expiry = now + timedelta(days=30)
                    current_status = "Inactive" if user.subscription_date else "Never activated"
                
                bot.send_message(
                    chat_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📅 <b>CONFIRM SUBSCRIPTION RENEWAL</b> 📅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Renew subscription for <b>{user.name}</b>:

• Current Status: <b>{current_status}</b>
• Current Balance: <b>${user.balance:.2f}</b>
• Fee: <b>$1.00</b>
• New Balance after renewal: <b>${user.balance - 1.0:.2f}</b>
• New Expiry Date: <b>{new_expiry.strftime('%Y-%m-%d')}</b>

<i>Click Confirm to renew the subscription.</i>
""",
                    parse_mode='HTML',
                    reply_markup=keyboard
                )
                
                # Update admin state
                admin_states[chat_id] = {
                    'action': 'renewing_subscription',
                    'user_id': user.id
                }
                
        except ValueError:
            bot.send_message(
                chat_id,
                "Invalid Telegram ID. Please enter a numeric ID.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                    KeyboardButton('🔙 Back to Subscription Management')
                )
            )
        except Exception as e:
            logger.error(f"Error processing subscription user ID: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(
                chat_id,
                "Error processing user ID. Please try again.",
                reply_markup=ReplyKeyboardMarkup(resize_keyboard=True).add(
                    KeyboardButton('🔙 Back to Subscription Management')
                )
            )
        finally:
            safe_close_session(session)
    
    @staticmethod
    def handle_subscription_renewal(bot, call):
        """Handle subscription renewal confirmation/cancellation"""
        chat_id = call.message.chat.id
        message_id = call.message.message_id
        
        if not AdminSection.is_admin(chat_id):
            bot.answer_callback_query(call.id, "Admin access required")
            return
            
        if call.data == "cancel_sub_renewal":
            # Cancel renewal
            bot.edit_message_text(
                "Subscription renewal cancelled.",
                chat_id=chat_id,
                message_id=message_id
            )
            
            # Clear admin state
            admin_states.pop(chat_id, None)
            
            bot.answer_callback_query(call.id, "Renewal cancelled")
            return
            
        try:
            # Extract user ID from callback data
            user_id = int(call.data.split('_')[-1])
            
            session = get_session()
            user = session.query(User).filter_by(id=user_id).first()
            
            if not user:
                bot.answer_callback_query(call.id, "User not found")
                bot.edit_message_text(
                    "User not found. Renewal cancelled.",
                    chat_id=chat_id,
                    message_id=message_id
                )
                return
                
            # Check if user has enough balance
            if user.balance < 1.0:
                bot.answer_callback_query(call.id, "Insufficient balance")
                bot.edit_message_text(
                    f"""
⚠️ <b>INSUFFICIENT BALANCE</b> ⚠️

User <b>{user.name}</b> doesn't have sufficient balance.
Please add balance before renewing.

• Current Balance: <b>${user.balance:.2f}</b>
• Required: <b>$1.00</b>
""",
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
                return
                
            # Process renewal
            previous_balance = user.balance
            user.balance -= 1.0
            
            # Update subscription date
            now = datetime.utcnow()
            if user.subscription_date and (now - user.subscription_date).days < 30:
                # Subscription is still active - extend from current expiry
                new_expiry = user.subscription_date + timedelta(days=30)
            else:
                # Subscription is expired or never activated
                new_expiry = now + timedelta(days=30)
                
            user.subscription_date = new_expiry - timedelta(days=30)  # Store start date
            
            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                amount=-1.0,
                transaction_type="subscription_renewal",
                description=f"Subscription renewal by administrator",
                status="completed"
            )
            session.add(transaction)
            
            session.commit()
            
            # Notify admin
            bot.edit_message_text(
                f"""
✅ <b>SUBSCRIPTION RENEWED</b> ✅

Successfully renewed subscription for <b>{user.name}</b>.

• Previous Balance: <b>${previous_balance:.2f}</b>
• New Balance: <b>${user.balance:.2f}</b>
• Expiry Date: <b>{new_expiry.strftime('%Y-%m-%d')}</b>

<i>The user has been notified.</i>
""",
                chat_id=chat_id,
                message_id=message_id,
                parse_mode='HTML'
            )
            
            # Notify user
            try:
                bot.send_message(
                    user.telegram_id,
                    f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   ✅ <b>SUBSCRIPTION RENEWED</b> ✅  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

Your subscription has been renewed by an administrator.

<b>💰 PAYMENT DETAILS:</b>
• Previous balance: <b>${previous_balance:.2f}</b>
• Renewal fee: <b>$1.00</b>
• New balance: <b>${user.balance:.2f}</b>

<b>📅 SUBSCRIPTION INFO:</b>
• Status: <b>Active</b>
• Expiry Date: <b>{new_expiry.strftime('%Y-%m-%d')}</b>

<i>Thank you for your continued subscription!</i>
""",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Error notifying user about subscription renewal: {e}")
            
            # Clear admin state
            admin_states.pop(chat_id, None)
            
            bot.answer_callback_query(call.id, "Subscription renewed successfully")
            
        except Exception as e:
            logger.error(f"Error handling subscription renewal: {e}")
            logger.error(traceback.format_exc())
            bot.answer_callback_query(call.id, "Error processing renewal")
            bot.send_message(chat_id, "Error renewing subscription. Please try again.")
        finally:
            safe_close_session(session)


class SystemStats(AdminSection):
    """System statistics section of admin panel"""
    
    @staticmethod
    def show_system_stats(bot, message):
        """Show system statistics"""
        chat_id = message.chat.id
        
        if not AdminSection.is_admin(chat_id):
            return
        
        session = None
        try:
            session = get_session()
            
            # Get user stats
            total_users = session.query(func.count(User.id)).scalar()
            registered_today = session.query(func.count(User.id)).filter(
                User.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            ).scalar()
            
            # Get order stats
            total_orders = session.query(func.count(Order.id)).scalar()
            orders_today = session.query(func.count(Order.id)).filter(
                Order.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            ).scalar()
            
            # Get deposit stats
            total_deposits = session.query(func.count(PendingDeposit.id)).filter(
                PendingDeposit.status == 'Approved'
            ).scalar()
            deposits_today = session.query(func.count(PendingDeposit.id)).filter(
                PendingDeposit.status == 'Approved',
                PendingDeposit.updated_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            ).scalar()
            
            # Pending deposits
            pending_deposits = session.query(func.count(PendingDeposit.id)).filter(
                PendingDeposit.status == 'Pending'
            ).scalar()
            
            # Pending orders
            pending_orders = session.query(func.count(Order.id)).filter(
                Order.status == 'Processing'
            ).scalar()
            
            # Revenue stats
            total_revenue = session.query(func.sum(PendingDeposit.amount)).filter(
                PendingDeposit.status == 'Approved'
            ).scalar() or 0
            
            revenue_today = session.query(func.sum(PendingDeposit.amount)).filter(
                PendingDeposit.status == 'Approved',
                PendingDeposit.updated_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            ).scalar() or 0
            
            # Create message with stats
            message_text = f"""
╭━━━━━━━━━━━━━━━━━━━━━━━╮
   📊 <b>SYSTEM STATISTICS</b> 📊  
╰━━━━━━━━━━━━━━━━━━━━━━━╯

<b>User Statistics:</b>
• Total Users: <b>{total_users}</b>
• New Users Today: <b>{registered_today}</b>

<b>Order Statistics:</b>
• Total Orders: <b>{total_orders}</b>
• Orders Today: <b>{orders_today}</b>
• Pending Orders: <b>{pending_orders}</b>

<b>Deposit Statistics:</b>
• Total Deposits: <b>{total_deposits}</b>
• Deposits Today: <b>{deposits_today}</b>
• Pending Deposits: <b>{pending_deposits}</b>

<b>Revenue:</b>
• Total Revenue: <b>${total_revenue:.2f}</b>
• Revenue Today: <b>${revenue_today:.2f}</b>

<b>System Information:</b>
• Bot Status: <b>Online</b>
• Database Status: <b>Connected</b>
• Current Time: <b>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</b>
"""
            
            bot.send_message(
                chat_id,
                message_text,
                parse_mode='HTML'
            )
            
        except Exception as e:
            logger.error(f"Error showing system stats: {e}")
            logger.error(traceback.format_exc())
            bot.send_message(chat_id, "Error retrieving system statistics. Please try again.")
        finally:
            safe_close_session(session)


def setup_admin_handlers(bot):
    """
    Register all admin handlers for a Telegram bot
    
    Args:
        bot: A Telebot instance
    """
    # Admin dashboard
    @bot.message_handler(commands=['admin'])
    def admin_command(message):
        AdminSection.handle_admin_dashboard(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔐 Admin Dashboard')
    def admin_dashboard_menu(message):
        AdminSection.handle_admin_dashboard(bot, message)
    
    # Navigation handlers
    @bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Main Menu')
    def back_to_main(message):
        AdminSection.back_to_main_menu(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Admin')
    def back_to_admin(message):
        AdminSection.handle_admin_dashboard(bot, message)
    
    # User management
    @bot.message_handler(func=lambda msg: msg.text == '👥 User Management')
    def user_management(message):
        UserManagement.show_user_management(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '📋 List All Users')
    def list_users(message):
        UserManagement.list_all_users(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔍 Find User')
    def find_user(message):
        UserManagement.find_user_prompt(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔙 Back to User Management')
    def back_to_user_management(message):
        UserManagement.show_user_management(bot, message)
    
    # Handle user search
    @bot.message_handler(func=lambda msg: msg.chat.id in admin_states and admin_states[msg.chat.id] == 'waiting_for_user_search')
    def search_user_handler(message):
        UserManagement.search_user(bot, message)
    
    # User pagination
    @bot.callback_query_handler(func=lambda call: call.data.startswith('users_page_'))
    def handle_users_page(call):
        UserManagement.handle_users_pagination(bot, call)
    
    # User management callbacks
    @bot.callback_query_handler(func=lambda call: call.data.startswith('manage_user_'))
    def handle_manage_user_callback(call):
        UserManagement.handle_manage_user(bot, call)
    @bot.callback_query_handler(func=lambda call: call.data.startswith('ban_user_') or call.data.startswith('unban_user_'))
    def handle_ban_unban_callback(call):
        UserManagement.handle_manage_user(bot, call)
        
    @bot.callback_query_handler(func=lambda call: call.data.startswith('add_balance_'))
    def handle_add_balance_callback(call):
        UserManagement.handle_manage_user(bot, call)
    
    # Process balance addition
    @bot.message_handler(func=lambda msg: msg.chat.id in admin_states and 
                       isinstance(admin_states[msg.chat.id], dict) and 
                       admin_states[msg.chat.id].get('action') == 'adding_balance')
    def process_balance_amount_handler(message):
        UserManagement.process_balance_amount(bot, message)
    
    # Order management
    @bot.message_handler(func=lambda msg: msg.text == '📦 Order Management')
    def order_management_handler(message):
        OrderManagement.show_order_management(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '📋 List All Orders')
    def list_orders_handler(message):
        OrderManagement.list_all_orders(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Order Management')
    def back_to_order_management(message):
        OrderManagement.show_order_management(bot, message)
    
    # Order pagination
    @bot.callback_query_handler(func=lambda call: call.data.startswith('orders_page_'))
    def handle_orders_pagination_callback(call):
        OrderManagement.handle_orders_pagination(bot, call)
    
    # Order management callbacks
    @bot.callback_query_handler(func=lambda call: call.data.startswith('manage_order_'))
    def handle_manage_order_callback(call):
        OrderManagement.handle_manage_order(bot, call)
        
    @bot.callback_query_handler(func=lambda call: call.data.startswith('update_order_') or 
                              call.data.startswith('add_tracking_') or 
                              call.data.startswith('change_status_'))
    def handle_update_order_callback(call):
        OrderManagement.handle_update_order(bot, call)
    
    # Process order updates
    @bot.message_handler(func=lambda msg: msg.chat.id in admin_states and 
                       isinstance(admin_states[msg.chat.id], dict) and 
                       admin_states[msg.chat.id].get('action') in ['update', 'add', 'change'])
    def process_order_update_handler(message):
        OrderManagement.process_order_update(bot, message)
    
    # Deposit management
    @bot.message_handler(func=lambda msg: msg.text == '💰 Deposit Management')
    def deposit_management_handler(message):
        DepositManagement.show_deposit_management(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '📋 List Pending Deposits')
    def list_pending_deposits_handler(message):
        DepositManagement.list_pending_deposits(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🕒 Recent Deposits')
    def show_recent_deposits_handler(message):
        DepositManagement.show_recent_deposits(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Deposit Management')
    def back_to_deposit_management(message):
        DepositManagement.show_deposit_management(bot, message)
    
    # Deposit approval/rejection
    @bot.callback_query_handler(func=lambda call: call.data.startswith('approve_deposit_') or call.data.startswith('reject_deposit_'))
    def handle_deposit_approval_callback(call):
        DepositManagement.handle_deposit_approval(bot, call)
    
    # Subscription management
    @bot.message_handler(func=lambda msg: msg.text == '📅 Subscription Management')
    def subscription_management_handler(message):
        SubscriptionManagement.show_subscription_management(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '📊 Subscription Stats')
    def subscription_stats_handler(message):
        SubscriptionManagement.show_subscription_stats(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🕒 Expiring Soon')
    def expiring_soon_handler(message):
        SubscriptionManagement.show_expiring_subscriptions(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '✅ Renew Subscription')
    def renew_subscription_handler(message):
        SubscriptionManagement.show_renew_subscription(bot, message)
        
    @bot.message_handler(func=lambda msg: msg.text == '🔙 Back to Subscription Management')
    def back_to_subscription_management(message):
        SubscriptionManagement.show_subscription_management(bot, message)
    
    # Process subscription renewal
    @bot.message_handler(func=lambda msg: msg.chat.id in admin_states and admin_states[msg.chat.id] == 'waiting_for_subscription_user_id')
    def process_subscription_user_id_handler(message):
        SubscriptionManagement.process_subscription_user_id(bot, message)
    
    # Subscription renewal callbacks
    @bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_renew_') or call.data == 'cancel_sub_renewal')
    def handle_subscription_renewal_callback(call):
        SubscriptionManagement.handle_subscription_renewal(bot, call)
    @bot.callback_query_handler(func=lambda call: call.data.startswith('renew_sub_'))
    def renew_sub_callback(call):
        bot.send_message(
            call.message.chat.id, 
            "Feature coming soon: Direct subscription renewal from list. Please use the manual renewal option."
        )
    
    # System statistics
    @bot.message_handler(func=lambda msg: msg.text == '📊 System Stats')
    def system_stats_handler(message):
        SystemStats.show_system_stats(bot, message)

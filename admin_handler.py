#!/usr/bin/env python3
"""
Admin Panel Handlers

This module contains all the admin-related functionality for the Telegram bot,
including user management, order management, deposit management, and system statistics.
"""

import logging
import traceback
from datetime import datetime, timedelta
from telebot.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from models import User, Order, PendingApproval, PendingDeposit, Transaction
from database import get_session, safe_close_session
from sqlalchemy import func, text

logger = logging.getLogger(__name__)

def is_admin(chat_id, admin_ids):
    """Check if a user is an admin"""
    return chat_id in admin_ids

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
        KeyboardButton('⚙️ Bot Settings')
    )
    admin_menu.add(
        KeyboardButton('🔙 Back to Main Menu')
    )
    return admin_menu

def handle_admin_dashboard(bot, message, admin_ids):
    """Show admin dashboard with all admin features"""
    chat_id = message.chat.id

    if not is_admin(chat_id, admin_ids):
        bot.send_message(
            chat_id,
            "⚠️ You don't have permission to access the admin dashboard."
        )
        return

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
• ⚙️ <b>Bot Settings</b> - Configure bot settings

<i>Select any option to continue or go back to the main menu.</i>
""",
        parse_mode='HTML',
        reply_markup=create_admin_menu()
    )

def handle_deposit_approval(bot, call, admin_ids):
    """Handle deposit approval/rejection"""
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    session = None

    # Verify admin permission
    if not is_admin(chat_id, admin_ids):
        bot.answer_callback_query(call.id, "⚠️ Admin access required")
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
                    user.balance = amount_after_sub
                    user.subscription_date = now
                    subscription_deducted = True
                    subscription_renewal_msg = f"\n📅 Subscription renewed until {(now + timedelta(days=30)).strftime('%Y-%m-%d')}"

            deposit.status = 'Approved'
            session.commit()

            # Notify user
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

        else:  # reject
            deposit.status = 'Rejected'
            session.commit()

            # Notify user
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

    except Exception as e:
        logger.error(f"Error handling deposit approval: {e}")
        logger.error(traceback.format_exc())
        bot.answer_callback_query(call.id, "Error processing deposit")
    finally:
        safe_close_session(session)

def process_order_details(bot, message, order_id, admin_ids):
    """Process order details from admin"""
    chat_id = message.chat.id
    session = None

    if not is_admin(chat_id, admin_ids):
        return

    try:
        if message.text.lower() == 'cancel':
            bot.reply_to(message, "Order processing cancelled.")
            return

        # Parse order details
        try:
            order_details = message.text.strip().split('|')
            if len(order_details) != 3:
                raise ValueError("Invalid format")

            aliexpress_id, tracking, price = order_details
            price = float(price)

        except (ValueError, IndexError):
            bot.reply_to(message, "Invalid format. Please use: orderid|tracking|price")
            return

        session = get_session()
        order = session.query(Order).filter_by(id=order_id).first()

        if not order:
            bot.reply_to(message, "Order not found.")
            return

        user = session.query(User).filter_by(id=order.user_id).first()
        if not user:
            bot.reply_to(message, "User not found.")
            return

        # Store original balance
        original_balance = user.balance

        # Deduct order amount
        if price > 0:
            user.balance -= price

            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                amount=-price,
                transaction_type="order_payment",
                description=f"Payment for order #{order.order_number}",
                reference=aliexpress_id,
                status="completed"
            )
            session.add(transaction)

        # Update order details
        order.order_id = aliexpress_id
        order.tracking_number = tracking if tracking else None
        order.amount = price
        order.status = "Shipped" if tracking else "Processing"
        order.carrier = "Standard AliExpress Shipping"
        order.updated_at = datetime.utcnow()

        session.commit()

        # Notify user
        tracking_info = ""
        if tracking:
            clean_tracking = tracking.strip().replace(" ", "").replace("+", "%2B")      
            parcels_app_link = f"https://global.cainiao.com/detail.htm?mailNo={clean_tracking}&lang=en"
            tracking_info = f"""
<b>📬 TRACKING INFORMATION:</b>
• Number: <code>{tracking}</code>
• Carrier: <b>{order.carrier}</b>
• <a href="{parcels_app_link}">Track Package</a>
• <a href="https://aliexpress.com/trackOrder.htm">Track on AliExpress</a>
"""

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

        # Confirm to admin
        bot.reply_to(
            message,
            f"""
✅ Order updated successfully:
• Order #{order.order_number}
• ID: {aliexpress_id}
• Tracking: {tracking if tracking else "None"}
• Price: ${price:.2f}
• Status: {order.status}
• User balance: ${original_balance:.2f} → ${user.balance:.2f}
""",
            parse_mode='HTML'
        )

    except Exception as e:
        logger.error(f"Error processing order details: {e}")
        logger.error(traceback.format_exc())
        bot.reply_to(message, "Error processing order details. Please try again.")
    finally:
        safe_close_session(session)

def register_handlers(bot, admin_ids):
    """Register all admin handlers"""
    # Admin dashboard
    bot.message_handler(commands=['admin'])(
        lambda message: handle_admin_dashboard(bot, message, admin_ids)
    )
    
    # Admin menu button
    bot.message_handler(func=lambda msg: msg.text == '🔐 Admin Dashboard')(
        lambda message: handle_admin_dashboard(bot, message, admin_ids)
    )
    
    # User management
    bot.message_handler(func=lambda msg: msg.text == '👥 User Management')(
        lambda message: handle_user_management(bot, message, admin_ids)
    )

    # Handle deposit approval/rejection
    bot.callback_query_handler(func=lambda call: call.data.startswith('approve_deposit_') or call.data.startswith('reject_deposit_'))(
        lambda call: handle_deposit_approval(bot, call, admin_ids)
    )

    # Handle order processing
    bot.callback_query_handler(func=lambda call: call.data.startswith('process_order_'))(
        lambda call: process_order_details(bot, call.message, int(call.data.split('_')[-1]), admin_ids)
    )

#!/usr/bin/env python3
"""
Admin Order Command System

This script adds direct commands to the Telegram bot for admins to manage
orders without relying on inline buttons. This provides a reliable alternative
when Telegram inline buttons aren't working properly.

Commands:
- /orderupdate ORDER_ID STATUS - Update order status and notify user
- /orderlist - List recent orders
- /orderdetail ORDER_ID - Show detailed info about an order

Usage:
1. Run this script
2. It will create the necessary command handlers in bot.py
"""

import logging
import re
import shutil
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def add_admin_order_commands():
    """Add admin order command handlers to bot.py"""
    bot_file = 'bot.py'
    
    # Back up the file first
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{bot_file}.admin_orders_{timestamp}.bak"
    
    try:
        shutil.copy2(bot_file, backup_file)
        logger.info(f"Created backup: {backup_file}")
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return False
    
    # Read the current content
    with open(bot_file, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # Find the best place to add our new command handlers (before main function)
    main_func_pos = content.find('def main():')
    
    if main_func_pos == -1:
        logger.error("Could not find main() function in bot.py")
        return False
    
    # Find a position to insert our handlers (before main function)
    insert_pos = content.rfind('\n\n', 0, main_func_pos)
    
    if insert_pos == -1:
        insert_pos = main_func_pos
    
    # Command handlers for admin order management
    admin_order_handlers = """
# Direct admin command handlers for order management (alternative to buttons)
@bot.message_handler(commands=['orderupdate'])
def order_update_command(message):
    \"\"\"Update order status and notify user\"\"\"
    if not is_admin(message.chat.id):
        bot.reply_to(message, "⚠️ This command is only available to administrators.")
        return

    # Extract the command format
    text = message.text.strip()
    parts = text.split()
    
    # Check command format
    if len(parts) < 3:
        bot.reply_to(message, 
                     "⚠️ Incorrect command format. Please use:\\n"
                     "/orderupdate ORDER_ID STATUS\\n\\n"
                     "Example: /orderupdate 12345 Shipped\\n\\n"
                     "Available statuses: Processing, Shipped, Delivered, Cancelled")
        return
    
    try:
        # Extract order ID and status
        order_id = parts[1]
        status = parts[2]
        
        # Validate status
        valid_statuses = ['Processing', 'Shipped', 'Delivered', 'Cancelled']
        if status not in valid_statuses:
            bot.reply_to(message, 
                         f"⚠️ Invalid status. Please use one of: {', '.join(valid_statuses)}")
            return
        
        # Update the order in the database
        session = Session()
        try:
            order = session.query(Order).filter_by(id=order_id).first()
            
            if not order:
                bot.reply_to(message, f"⚠️ Order #{order_id} not found.")
                return
            
            # Get the previous status for notification purposes
            prev_status = order.status
            
            # Update the order status
            order.status = status
            order.updated_at = datetime.now()
            
            # Update delivery status based on order status
            if status == 'Processing':
                order.delivery_status = 'pending'
            elif status == 'Shipped': 
                order.delivery_status = 'in_transit'
            elif status == 'Delivered':
                order.delivery_status = 'delivered'
            elif status == 'Cancelled':
                order.delivery_status = 'cancelled'
            
            # Commit the change
            session.commit()
            
            # Send confirmation to admin
            bot.reply_to(message, f"✅ Order #{order_id} status updated from {prev_status} to {status}.")
            
            # Notify the user
            user_id = order.user_id
            try:
                bot.send_message(
                    user_id,
                    f"🔄 <b>Order Status Update</b>\\n\\n"
                    f"Your order #{order_id} status has been updated to: <b>{status}</b>\\n\\n"
                    f"If you have any questions, please contact customer support.",
                    parse_mode="HTML"
                )
                bot.send_message(message.chat.id, f"✅ User notification sent successfully.")
            except Exception as e:
                bot.send_message(
                    message.chat.id,
                    f"⚠️ Failed to send notification to user: {e}"
                )
                
        except Exception as e:
            session.rollback()
            bot.reply_to(message, f"❌ Error updating order: {e}")
            logger.error(f"Error updating order: {e}")
        finally:
            session.close()
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing command: {e}")
        logger.error(f"Error in order_update_command: {e}")

@bot.message_handler(commands=['orderlist'])
def order_list_command(message):
    \"\"\"List recent orders\"\"\"
    if not is_admin(message.chat.id):
        bot.reply_to(message, "⚠️ This command is only available to administrators.")
        return
        
    try:
        session = Session()
        orders = session.query(Order).order_by(Order.created_at.desc()).limit(10).all()
        
        if not orders:
            bot.reply_to(message, "No orders found.")
            return
        
        # Build message with order details
        response = "<b>Recent Orders</b>\\n\\n"
        
        for order in orders:
            user = session.query(User).filter_by(telegram_id=order.user_id).first()
            username = user.name if user and user.name else f"User ID: {order.user_id}"
            
            response += f"<b>Order #{order.id}</b>\\n"
            response += f"User: {username}\\n"
            response += f"Status: {order.status}\\n"
            response += f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}\\n"
            response += f"Details: /orderdetail_{order.id}\\n"
            response += f"Update: /orderupdate {order.id} [status]\\n\\n"
        
        bot.send_message(message.chat.id, response, parse_mode='HTML')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error listing orders: {e}")
        logger.error(f"Error in order_list_command: {e}")
    finally:
        session.close()

@bot.message_handler(regexp="^/orderdetail_([0-9]+)$")
def order_detail_inline_command(message):
    \"\"\"Handle the inline order detail button\"\"\"
    if not is_admin(message.chat.id):
        bot.reply_to(message, "⚠️ This command is only available to administrators.")
        return
    
    # Extract order ID from command
    match = re.match(r"/orderdetail_([0-9]+)", message.text)
    if match:
        order_id = match.group(1)
        _show_order_details(message.chat.id, order_id)
    else:
        bot.reply_to(message, "⚠️ Invalid order detail command.")

@bot.message_handler(commands=['orderdetail'])
def order_detail_command(message):
    \"\"\"Show detailed info about an order\"\"\"
    if not is_admin(message.chat.id):
        bot.reply_to(message, "⚠️ This command is only available to administrators.")
        return
    
    # Extract the command format
    text = message.text.strip()
    parts = text.split()
    
    # Check command format
    if len(parts) < 2:
        bot.reply_to(message, 
                     "⚠️ Incorrect command format. Please use:\\n"
                     "/orderdetail ORDER_ID")
        return
    
    try:
        order_id = parts[1]
        _show_order_details(message.chat.id, order_id)
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing command: {e}")
        logger.error(f"Error in order_detail_command: {e}")

def _show_order_details(chat_id, order_id):
    \"\"\"Helper function to show order details\"\"\"
    try:
        session = Session()
        order = session.query(Order).filter_by(id=order_id).first()
        
        if not order:
            bot.send_message(chat_id, f"⚠️ Order #{order_id} not found.")
            return
        
        # Get user info
        user = session.query(User).filter_by(telegram_id=order.user_id).first()
        username = user.name if user and user.name else f"User ID: {order.user_id}"
        
        # Build detailed order info
        response = f"<b>Order #{order.id} Details</b>\\n\\n"
        response += f"<b>User:</b> {username}\\n"
        response += f"<b>User ID:</b> {order.user_id}\\n"
        response += f"<b>Status:</b> {order.status}\\n"
        
        # Include the details only if available
        if order.order_number:
            response += f"<b>Order Number:</b> {order.order_number}\\n"
        if order.order_id:
            response += f"<b>Order ID:</b> {order.order_id}\\n"
        if order.tracking_number:
            response += f"<b>Tracking:</b> {order.tracking_number}\\n"
        if order.carrier:
            response += f"<b>Carrier:</b> {order.carrier}\\n"
            
        response += f"<b>Created:</b> {order.created_at.strftime('%Y-%m-%d %H:%M')}\\n"
        
        if order.updated_at:
            response += f"<b>Updated:</b> {order.updated_at.strftime('%Y-%m-%d %H:%M')}\\n"
            
        if order.delivery_status:
            response += f"<b>Delivery Status:</b> {order.delivery_status}\\n"
            
        if order.estimated_delivery:
            response += f"<b>Est. Delivery:</b> {order.estimated_delivery.strftime('%Y-%m-%d')}\\n"
            
        response += f"<b>Product Link:</b> {order.product_link}\\n\\n"
        
        # Add action buttons at the bottom
        response += "<b>Update Status:</b>\\n"
        response += f"/orderupdate {order.id} Processing\\n"
        response += f"/orderupdate {order.id} Shipped\\n"
        response += f"/orderupdate {order.id} Delivered\\n"
        response += f"/orderupdate {order.id} Cancelled\\n"
        
        bot.send_message(chat_id, response, parse_mode='HTML')
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Error retrieving order details: {e}")
        logger.error(f"Error in _show_order_details: {e}")
    finally:
        session.close()

"""
    
    # Insert the handlers
    new_content = content[:insert_pos] + admin_order_handlers + content[insert_pos:]
    
    # Write the modified content back to the file
    with open(bot_file, 'w', encoding='utf-8') as file:
        file.write(new_content)
    
    logger.info("✅ Added admin order command handlers to bot.py")
    print("✅ Successfully added admin order command handlers!")
    print("")
    print("Now you can use these admin commands in Telegram:")
    print("  /orderlist - List recent orders")
    print("  /orderdetail 12345 - View details of order #12345")
    print("  /orderupdate 12345 Shipped - Update order #12345 to 'Shipped' status")
    print("")
    print("These commands work without buttons and provide direct order management capabilities.")
    
    return True

if __name__ == '__main__':
    add_admin_order_commands()

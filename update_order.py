"""
Direct Order Update Tool

This standalone script provides a command-line interface for directly updating orders
in the database without relying on Telegram bot functionality. It's a reliable fallback
when the bot's button system or command handlers aren't working.

Usage:
  python update_order.py list
  python update_order.py view ORDER_ID
  python update_order.py update ORDER_ID STATUS
"""

import os
import sys
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, ForeignKey, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable not set")
    sys.exit(1)

# Create database engine
engine = create_engine(DATABASE_URL)
Base = declarative_base()
Session = sessionmaker(bind=engine)

# Define models
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    email = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    is_verified = Column(Boolean, default=False)
    registration_complete = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    subscription_date = Column(DateTime, nullable=True)
    last_subscription_reminder = Column(DateTime, nullable=True)
    referred_by_id = Column(Integer, nullable=True)
    referral_code = Column(String, nullable=True)
    referral_points = Column(Integer, default=0)

class Order(Base):
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)  # This is the user's database ID
    order_number = Column(String, nullable=True)
    amount = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    estimated_delivery = Column(DateTime, nullable=True)
    status = Column(String, default='Processing')
    delivery_status = Column(String, default='pending')
    product_link = Column(String, nullable=True)  # This is the order link
    order_id = Column(String, nullable=True)  # External order ID
    tracking_number = Column(String, nullable=True)
    carrier = Column(String, nullable=True)

def list_orders():
    """List all orders"""
    session = Session()
    try:
        print("\n===== ORDERS LIST =====")
        print(f"{'ID':<5} {'USER':<20} {'DATE':<12} {'STATUS':<12} {'AMOUNT':<10}")
        print("-" * 60)
        
        orders = session.query(Order).order_by(desc(Order.created_at)).all()
        for order in orders:
            # Get user info
            user = session.query(User).filter_by(id=order.user_id).first()
            user_name = user.name if user and user.name else f"User {order.user_id}"
            
            # Truncate name if too long
            if len(user_name) > 18:
                user_name = user_name[:16] + ".."
            
            date_str = order.created_at.strftime('%Y-%m-%d')
            print(f"{order.id:<5} {user_name:<20} {date_str:<12} {order.status:<12} ${order.amount:<10.2f}")
        
        print("-" * 60)
        print(f"Total Orders: {len(orders)}")
        
    except Exception as e:
        logger.error(f"Error listing orders: {e}")
    finally:
        session.close()

def view_order(order_id):
    """View details of a specific order"""
    session = Session()
    try:
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            print(f"Order #{order_id} not found.")
            return
        
        # Get user info
        user = session.query(User).filter_by(id=order.user_id).first()
        user_name = user.name if user else "Unknown"
        
        print("\n===== ORDER DETAILS =====")
        print(f"Order ID:       #{order.id}")
        print(f"Order Number:   {order.order_number or 'Not assigned'}")
        print(f"Status:         {order.status}")
        print(f"Customer:       {user_name} (ID: {order.user_id})")
        print(f"Amount:         ${order.amount:.2f}")
        print(f"Created:        {order.created_at.strftime('%Y-%m-%d %H:%M')}")
        print(f"Updated:        {order.updated_at.strftime('%Y-%m-%d %H:%M') if order.updated_at else 'N/A'}")
        print(f"Product Link:   {order.product_link or 'Not available'}")
        print(f"External ID:    {order.order_id or 'Not available'}")
        print(f"Tracking:       {order.tracking_number or 'Not available'}")
        print(f"Carrier:        {order.carrier or 'Not available'}")
        print(f"Delivery:       {order.delivery_status}")
        if order.estimated_delivery:
            print(f"Est. Delivery:  {order.estimated_delivery.strftime('%Y-%m-%d')}")
        
        print("\nAvailable actions:")
        print(f"  python update_order.py update {order.id} Processing")
        print(f"  python update_order.py update {order.id} Shipped")
        print(f"  python update_order.py update {order.id} Delivered")
        print(f"  python update_order.py update {order.id} Cancelled")
        
    except Exception as e:
        logger.error(f"Error viewing order: {e}")
    finally:
        session.close()

def update_order(order_id, status):
    """Update the status of an order"""
    session = Session()
    try:
        # Get the order
        order = session.query(Order).filter_by(id=order_id).first()
        if not order:
            print(f"Order #{order_id} not found.")
            return
        
        # Validate status
        valid_statuses = ['Processing', 'Shipped', 'Delivered', 'Cancelled']
        if status not in valid_statuses:
            print(f"Invalid status. Please use one of: {', '.join(valid_statuses)}")
            return
        
        # Store previous status for confirmation message
        prev_status = order.status
        
        # Update the order
        order.status = status
        
        # Update delivery status based on order status
        if status == 'Processing':
            order.delivery_status = 'pending'
        elif status == 'Shipped': 
            order.delivery_status = 'in_transit'
        elif status == 'Delivered':
            order.delivery_status = 'delivered'
        elif status == 'Cancelled':
            order.delivery_status = 'cancelled'
        
        # Save the changes
        order.updated_at = datetime.now()
        session.commit()
        
        print(f"\n✅ Order #{order_id} updated successfully")
        print(f"Previous status: {prev_status}")
        print(f"New status:      {status}")
        
        # Get user info for notification
        user = session.query(User).filter_by(id=order.user_id).first()
        if user:
            # Recommend notifying the customer
            print("\nIMPORTANT: Please manually notify the customer about this status change.")
            print(f"User Name:       {user.name}")
            print(f"User Telegram ID: {user.telegram_id}")
        else:
            print("\nWARNING: Could not find user information for notification.")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating order: {e}")
    finally:
        session.close()

def main():
    """Main function to handle command-line arguments"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python update_order.py list")
        print("  python update_order.py view ORDER_ID")
        print("  python update_order.py update ORDER_ID STATUS")
        return
    
    command = sys.argv[1].lower()
    
    if command == "list":
        list_orders()
    elif command == "view":
        if len(sys.argv) < 3:
            print("Please provide an order ID")
            return
        view_order(sys.argv[2])
    elif command == "update":
        if len(sys.argv) < 4:
            print("Please provide an order ID and status")
            return
        update_order(sys.argv[2], sys.argv[3])
    else:
        print(f"Unknown command: {command}")
        print("Available commands: list, view, update")

if __name__ == "__main__":
    main()

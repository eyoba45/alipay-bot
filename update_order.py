#!/usr/bin/env python3
"""
Order Update Utility

This standalone script lets you update order status directly from the command line,
without relying on Telegram bot buttons. This is useful when the buttons aren't working.

Usage:
  python update_order.py list                  - List recent orders
  python update_order.py status ORDER_ID       - Show status of specific order
  python update_order.py update ORDER_ID STATUS - Update order status
  
Available statuses: Processing, Shipped, Delivered, Cancelled
"""

import os
import sys
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize SQLAlchemy
Base = declarative_base()

# Define Order model (matching your actual database schema)
class Order(Base):
    __tablename__ = 'orders'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    order_number = Column(Integer, nullable=True)
    product_link = Column(String, nullable=True)
    order_id = Column(String, nullable=True)
    tracking_number = Column(String, nullable=True)
    carrier = Column(String, nullable=True)
    status = Column(String, nullable=False, default='Pending')
    amount = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=True, onupdate=datetime.now)
    delivery_status = Column(String, nullable=True)
    estimated_delivery = Column(DateTime, nullable=True)

# Define User model for reference (matching actual database schema)
class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, nullable=False, unique=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    is_verified = Column(Boolean, nullable=True)
    registration_complete = Column(Boolean, nullable=True)
    is_banned = Column(Boolean, nullable=True)
    balance = Column(Float, nullable=True)
    subscription_date = Column(DateTime, nullable=True)
    last_subscription_reminder = Column(DateTime, nullable=True)
    referred_by_id = Column(Integer, nullable=True)
    referral_points = Column(Integer, nullable=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    email = Column(String, nullable=True)
    referral_code = Column(String, nullable=True)

def initialize_db():
    """Initialize database connection"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    try:
        engine = create_engine(database_url)
        Session = sessionmaker(bind=engine)
        return Session()
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        sys.exit(1)

def list_orders(session):
    """List recent orders"""
    try:
        orders = session.query(Order).order_by(Order.created_at.desc()).limit(15).all()
        
        if not orders:
            print("No orders found.")
            return
        
        print("\n===== RECENT ORDERS =====")
        for order in orders:
            user = session.query(User).filter_by(telegram_id=order.user_id).first()
            username = user.name if user else "Unknown"
            
            print(f"\nOrder #{order.id}")
            print(f"User: {username} (ID: {order.user_id})")
            print(f"Status: {order.status}")
            print(f"Product Link: {order.product_link}")
            if order.order_number:
                print(f"Order Number: {order.order_number}")
            print(f"Created: {order.created_at.strftime('%Y-%m-%d %H:%M')}")
            if order.updated_at:
                print(f"Updated: {order.updated_at.strftime('%Y-%m-%d %H:%M')}")
            if order.delivery_status:
                print(f"Delivery Status: {order.delivery_status}")
            
        print("\nTo update an order, use: python update_order.py update ORDER_ID STATUS")
        print("Available statuses: Processing, Shipped, Delivered, Cancelled")
        
    except Exception as e:
        logger.error(f"Error listing orders: {e}")
        print(f"Error: {e}")

def show_order_status(session, order_id):
    """Show status of a specific order"""
    try:
        order = session.query(Order).filter_by(id=order_id).first()
        
        if not order:
            print(f"Order #{order_id} not found.")
            return
        
        user = session.query(User).filter_by(telegram_id=order.user_id).first()
        username = user.name if user else "Unknown"
        
        print(f"\n===== ORDER #{order.id} DETAILS =====")
        print(f"User: {username} (ID: {order.user_id})")
        print(f"Status: {order.status}")
        print(f"Product Link: {order.product_link}")
        if order.order_number:
            print(f"Order Number: {order.order_number}")
        if order.order_id:
            print(f"Order ID: {order.order_id}")
        if order.tracking_number:
            print(f"Tracking #: {order.tracking_number}")
        if order.carrier:
            print(f"Carrier: {order.carrier}")
        print(f"Created: {order.created_at.strftime('%Y-%m-%d %H:%M')}")
        if order.updated_at:
            print(f"Updated: {order.updated_at.strftime('%Y-%m-%d %H:%M')}")
        if order.delivery_status:
            print(f"Delivery Status: {order.delivery_status}")
        if order.estimated_delivery:
            print(f"Estimated Delivery: {order.estimated_delivery.strftime('%Y-%m-%d')}")
        print(f"Amount: {order.amount if order.amount else 'Not specified'}")
        
        print("\nTo update this order, use: python update_order.py update ORDER_ID STATUS")
        print("Available statuses: Processing, Shipped, Delivered, Cancelled")
        
    except Exception as e:
        logger.error(f"Error showing order status: {e}")
        print(f"Error: {e}")

def update_order_status(session, order_id, status):
    """Update the status of an order"""
    # Validate status
    valid_statuses = ['Processing', 'Shipped', 'Delivered', 'Cancelled']
    if status not in valid_statuses:
        print(f"Invalid status. Please use one of: {', '.join(valid_statuses)}")
        return
    
    try:
        order = session.query(Order).filter_by(id=order_id).first()
        
        if not order:
            print(f"Order #{order_id} not found.")
            return
        
        # Save previous status for reporting
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
        
        # Commit the changes
        session.commit()
        
        print(f"✅ Order #{order_id} updated from '{prev_status}' to '{status}'")
        print(f"✅ Delivery status updated to '{order.delivery_status}'")
        print("\nTo notify the user, you'll need to send a message through the bot.")
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating order: {e}")
        print(f"Error: {e}")

def main():
    """Main function to handle command line arguments"""
    if len(sys.argv) < 2:
        print("Please provide a command.")
        print("Usage:")
        print("  python update_order.py list                   - List recent orders")
        print("  python update_order.py status ORDER_ID        - Show status of specific order")
        print("  python update_order.py update ORDER_ID STATUS - Update order status")
        return
    
    command = sys.argv[1].lower()
    
    # Initialize database session
    session = initialize_db()
    
    try:
        if command == "list":
            list_orders(session)
        
        elif command == "status":
            if len(sys.argv) < 3:
                print("Please provide an order ID.")
                return
            
            order_id = sys.argv[2]
            show_order_status(session, order_id)
        
        elif command == "update":
            if len(sys.argv) < 4:
                print("Please provide an order ID and status.")
                print("Example: python update_order.py update 12345 Shipped")
                return
            
            order_id = sys.argv[2]
            status = sys.argv[3]
            update_order_status(session, order_id, status)
        
        else:
            print(f"Unknown command: {command}")
            print("Available commands: list, status, update")
    
    finally:
        session.close()

if __name__ == "__main__":
    main()

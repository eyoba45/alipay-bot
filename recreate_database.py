#!/usr/bin/env python3
import os
import sys
import logging
from database import get_connection

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def recreate_tables():
    """Drop and recreate all tables"""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        logger.info("Starting database schema recreation")

        # Drop tables in correct order to handle dependencies
        logger.info("Dropping existing tables...")
        cur.execute("""
            DROP TABLE IF EXISTS pending_deposits CASCADE;
            DROP TABLE IF EXISTS orders CASCADE;
            DROP TABLE IF EXISTS pending_approvals CASCADE;
            DROP TABLE IF EXISTS users CASCADE;
        """)

        # Create tables in correct order
        logger.info("Creating users table...")
        cur.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                subscription_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_subscription_reminder TIMESTAMP NULL,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(255),
                address TEXT,
                balance FLOAT DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        logger.info("Creating pending_approvals table...")
        cur.execute("""
            CREATE TABLE pending_approvals (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(255) NOT NULL,
                address TEXT NOT NULL,
                payment_status VARCHAR(50) DEFAULT 'pending',
                tx_ref VARCHAR(255) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        logger.info("Creating orders table...")
        cur.execute("""
            CREATE TABLE orders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                order_number INTEGER NOT NULL,
                product_link TEXT NOT NULL,
                order_id VARCHAR(255),
                tracking_number VARCHAR(255),
                status VARCHAR(50) DEFAULT 'Processing',
                amount FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        logger.info("Creating pending_deposits table...")
        cur.execute("""
            CREATE TABLE pending_deposits (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount FLOAT NOT NULL,
                tx_ref VARCHAR(255) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) DEFAULT 'Processing',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Commit the transaction
        conn.commit()
        logger.info("✅ All tables created successfully with correct schema!")
        print("✅ Database tables recreated successfully!")

    except Exception as e:
        logger.error(f"Error recreating database: {e}")
        if conn:
            conn.rollback()
        print(f"❌ Error recreating database: {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    recreate_tables()

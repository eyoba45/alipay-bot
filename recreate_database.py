
import os
import logging
import sys
import psycopg2
from psycopg2 import sql

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_connection():
    """Get a database connection"""
    try:
        # Get database URL from environment
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            logger.error("DATABASE_URL environment variable is not set")
            sys.exit(1)
            
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        sys.exit(1)

def recreate_tables():
    """Drop and recreate all tables with proper schema"""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        logger.info("Starting database schema recreation")
        
        # Disable triggers temporarily
        cur.execute("SET session_replication_role = 'replica';")
        
        # Step 1: Drop all tables - with CASCADE to handle dependencies
        logger.info("Dropping all existing tables...")
        cur.execute("""
        DROP TABLE IF EXISTS pending_deposits CASCADE;
        DROP TABLE IF EXISTS orders CASCADE;
        DROP TABLE IF EXISTS pending_approvals CASCADE;
        DROP TABLE IF EXISTS users CASCADE;
        """)
        logger.info("All tables dropped successfully")
        
        # Step 2: Create tables with correct schema
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) DEFAULT 'Processing',
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        
        # Re-enable triggers
        cur.execute("SET session_replication_role = 'origin';")
        
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

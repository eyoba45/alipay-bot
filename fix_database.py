
import os
import psycopg2
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_db():
    try:
        return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=5)
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

def fix_database_schema():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Check each table and add missing columns
                
                # First drop all tables to start fresh
                logger.info("Dropping all tables to recreate schema...")
                cur.execute("DROP TABLE IF EXISTS pending_deposits CASCADE")
                cur.execute("DROP TABLE IF EXISTS orders CASCADE")
                cur.execute("DROP TABLE IF EXISTS users CASCADE")
                cur.execute("DROP TABLE IF EXISTS pending_approvals CASCADE")
                
                # Create tables with correct schema
                logger.info("Creating users table...")
                cur.execute('''
                    CREATE TABLE users (
                        chat_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        phone TEXT,
                        address TEXT,
                        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                logger.info("Creating pending_approvals table...")
                cur.execute('''
                    CREATE TABLE pending_approvals (
                        chat_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        phone TEXT,
                        address TEXT,
                        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                logger.info("Creating pending_deposits table...")
                cur.execute('''
                    CREATE TABLE pending_deposits (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT,
                        amount TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'pending',
                        FOREIGN KEY (chat_id) REFERENCES users(chat_id)
                    )
                ''')
                
                logger.info("Creating orders table...")
                cur.execute('''
                    CREATE TABLE orders (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT,
                        item_name TEXT,
                        quantity INTEGER,
                        total_price NUMERIC,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'pending',
                        FOREIGN KEY (chat_id) REFERENCES users(chat_id)
                    )
                ''')
                
                conn.commit()
                logger.info("Database schema fixed successfully!")
                print("✅ Database schema has been recreated with the correct columns!")
    except Exception as e:
        logger.error(f"Error fixing database schema: {e}")
        print(f"❌ Error fixing database schema: {e}")

if __name__ == "__main__":
    fix_database_schema()

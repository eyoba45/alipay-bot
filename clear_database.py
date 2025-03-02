
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

def clear_all_tables():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Clear all tables
                logger.info("Clearing all tables...")
                
                # Disable foreign key checks temporarily
                cur.execute("SET CONSTRAINTS ALL DEFERRED")
                
                # Clear tables
                cur.execute("TRUNCATE TABLE pending_deposits CASCADE")
                logger.info("Cleared pending_deposits table")
                
                cur.execute("TRUNCATE TABLE orders CASCADE")
                logger.info("Cleared orders table")
                
                cur.execute("TRUNCATE TABLE users CASCADE")
                logger.info("Cleared users table")
                
                cur.execute("TRUNCATE TABLE pending_approvals CASCADE")
                logger.info("Cleared pending_approvals table")
                
                # Re-enable foreign key checks
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
                
                conn.commit()
                logger.info("All tables have been cleared successfully!")
                print("✅ Database cleared successfully! All users and data have been removed.")
    except Exception as e:
        logger.error(f"Error clearing tables: {e}")
        print(f"❌ Error clearing database: {e}")

if __name__ == "__main__":
    clear_all_tables()

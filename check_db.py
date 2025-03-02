import os
import logging
import psycopg2
from psycopg2.extras import DictCursor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Get a database connection"""
    try:
        # Get database URL from environment
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            logger.error("DATABASE_URL environment variable is not set")
            return None

        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        return None

def check_database():
    """Check database connection and tables"""
    try:
        conn = get_db_connection()
        if not conn:
            print("❌ Could not connect to database. Check DATABASE_URL environment variable.")
            return

        with conn:
            with conn.cursor() as cur:
                # Check if tables exist
                cur.execute('''
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                ''')
                tables = [table[0] for table in cur.fetchall()]

                print(f"📊 Database connected successfully!")
                print(f"Found {len(tables)} tables: {', '.join(tables)}")

                # Check users count
                if 'users' in tables:
                    cur.execute("SELECT COUNT(*) FROM users")
                    user_count = cur.fetchone()[0]
                    print(f"Found {user_count} users in the database")
                else:
                    print("Users table does not exist")

                # Create tables if they don't exist
                print("\nCreating tables if they don't exist...")

                # Create users table
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        chat_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                conn.commit()
                print("✅ Tables created/verified successfully!")

                # Check tables again
                cur.execute('''
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                ''')
                tables = [table[0] for table in cur.fetchall()]
                print(f"Now have {len(tables)} tables: {', '.join(tables)}")
    except Exception as e:
        print(f"❌ Error checking database: {str(e)}")

if __name__ == "__main__":
    check_database()
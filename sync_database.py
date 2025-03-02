
import os
import psycopg2
import logging
from datetime import datetime

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

def sync_users_to_db(users_dict):
    """Sync in-memory users to database"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Could not connect to database for syncing users")
            return False
            
        with conn:
            with conn.cursor() as cur:
                # First clear tables to avoid duplicates or conflicts
                cur.execute("DELETE FROM pending_approvals")
                cur.execute("DELETE FROM pending_deposits")
                # Don't delete users table as it would break foreign key constraints
                
                # Insert users data
                for chat_id, user_data in users_dict.items():
                    # Check if user exists
                    cur.execute("SELECT 1 FROM users WHERE chat_id = %s", (chat_id,))
                    exists = cur.fetchone() is not None
                    
                    if exists:
                        # Update existing user
                        update_fields = []
                        update_values = []
                        
                        for key, value in user_data.items():
                            if key != 'chat_id':  # Skip primary key
                                update_fields.append(f"{key} = %s")
                                update_values.append(value)
                        
                        if update_fields:
                            update_values.append(chat_id)  # Add chat_id for WHERE clause
                            query = f"UPDATE users SET {', '.join(update_fields)} WHERE chat_id = %s"
                            cur.execute(query, update_values)
                    else:
                        # Insert new user
                        columns = ['chat_id']
                        values = [chat_id]
                        placeholders = ['%s']
                        
                        for key, value in user_data.items():
                            if key != 'chat_id':  # Skip duplicate primary key
                                columns.append(key)
                                values.append(value)
                                placeholders.append('%s')
                        
                        query = f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
                        cur.execute(query, values)
                
                logger.info(f"Successfully synced {len(users_dict)} users to database")
        return True
    except Exception as e:
        logger.error(f"Error syncing users to database: {str(e)}")
        return False

def sync_pending_approvals(pending_dict):
    """Sync pending approvals to database"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Could not connect to database for syncing pending approvals")
            return False
            
        with conn:
            with conn.cursor() as cur:
                # Clear existing pending approvals
                cur.execute("DELETE FROM pending_approvals")
                
                # Insert new pending approvals
                for chat_id, user_data in pending_dict.items():
                    columns = ['chat_id']
                    values = [chat_id]
                    placeholders = ['%s']
                    
                    for key, value in user_data.items():
                        if key != 'chat_id':  # Skip duplicate primary key
                            columns.append(key)
                            values.append(value)
                            placeholders.append('%s')
                    
                    query = f"INSERT INTO pending_approvals ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
                    cur.execute(query, values)
                
                logger.info(f"Successfully synced {len(pending_dict)} pending approvals to database")
        return True
    except Exception as e:
        logger.error(f"Error syncing pending approvals to database: {str(e)}")
        return False

def sync_pending_deposits(pending_deposits_dict):
    """Sync pending deposits to database"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Could not connect to database for syncing pending deposits")
            return False
            
        with conn:
            with conn.cursor() as cur:
                # Clear existing pending deposits
                cur.execute("DELETE FROM pending_deposits")
                
                # Insert new pending deposits
                for chat_id, amount in pending_deposits_dict.items():
                    cur.execute(
                        "INSERT INTO pending_deposits (chat_id, amount, timestamp) VALUES (%s, %s, %s)",
                        (chat_id, amount, datetime.now())
                    )
                
                logger.info(f"Successfully synced {len(pending_deposits_dict)} pending deposits to database")
        return True
    except Exception as e:
        logger.error(f"Error syncing pending deposits to database: {str(e)}")
        return False

def sync_all_data(users, pending_approvals, pending_deposits):
    """Sync all in-memory data to database"""
    success_users = sync_users_to_db(users)
    success_approvals = sync_pending_approvals(pending_approvals)
    success_deposits = sync_pending_deposits(pending_deposits)
    
    return success_users and success_approvals and success_deposits

if __name__ == "__main__":
    print("This script is meant to be imported, not run directly.")

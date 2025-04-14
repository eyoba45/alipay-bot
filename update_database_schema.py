"""
Update Database Schema for Referral System

This script adds the referral columns to the users table
and creates the referral-related tables.
"""
import os
import sys
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('update_schema')

def get_database_url():
    """Get database URL from environment variables"""
    return os.environ.get('DATABASE_URL')

def update_schema():
    """Update the database schema to add referral system tables"""
    db_url = get_database_url()
    if not db_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    engine = create_engine(db_url)
    logger.info("Connected to database")
    
    try:
        with engine.connect() as conn:
            # Add referral columns to users table
            conn.execute(text("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS referral_code VARCHAR,
                ADD COLUMN IF NOT EXISTS referred_by_id INTEGER,
                ADD COLUMN IF NOT EXISTS referral_points INTEGER DEFAULT 0;
            """))
            
            # Create referrals table if it doesn't exist
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id SERIAL PRIMARY KEY,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER NOT NULL,
                    referral_code VARCHAR NOT NULL,
                    status VARCHAR DEFAULT 'pending',
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referrer_id) REFERENCES users(id),
                    FOREIGN KEY (referred_id) REFERENCES users(id)
                );
            """))
            
            # Create referral_rewards table if it doesn't exist
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS referral_rewards (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    referral_id INTEGER,
                    points INTEGER NOT NULL,
                    reward_type VARCHAR NOT NULL,
                    description VARCHAR NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (referral_id) REFERENCES referrals(id)
                );
            """))
            
            conn.commit()
            logger.info("Database schema updated successfully")
            return True
    except SQLAlchemyError as e:
        logger.error(f"Error updating schema: {e}")
        return False

if __name__ == "__main__":
    if update_schema():
        print("✅ Database schema updated successfully!")
    else:
        print("❌ Failed to update database schema. Check the logs for details.")
        sys.exit(1)

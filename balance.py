#!/usr/bin/env python3
"""
Add missing balance_updated column to pending_deposits table in production database
"""
import os
import logging
import sys
from sqlalchemy import create_engine, text

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def add_balance_updated_column():
    """Add the missing balance_updated column to the pending_deposits table"""
    try:
        # Get database URL from environment
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            logger.error("DATABASE_URL environment variable not set")
            return False
            
        logger.info(f"Connecting to database: {db_url.split('@')[1] if '@' in db_url else '(masked)'}")
        
        # Create engine with minimal connection pool - production database may have connection limits
        engine = create_engine(
            db_url,
            pool_size=2,
            max_overflow=5,
            pool_timeout=30,
            pool_recycle=1800
        )
        
        # Add the column using direct SQL
        with engine.connect() as conn:
            # First check if the column exists
            try:
                result = conn.execute(text("SELECT balance_updated FROM pending_deposits LIMIT 1"))
                logger.info("✅ balance_updated column already exists")
                return True
            except Exception:
                logger.info("Column does not exist, will add it now")
                
            # Try to add the column
            try:
                conn.execute(text("ALTER TABLE pending_deposits ADD COLUMN balance_updated BOOLEAN DEFAULT FALSE"))
                conn.commit()
                logger.info("✅ Successfully added balance_updated column")
                
                # Verify the column was added
                result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'pending_deposits' AND column_name = 'balance_updated'"))
                if result.scalar():
                    logger.info("✅ Verified balance_updated column exists")
                    return True
                else:
                    logger.error("❌ Column was not added successfully")
                    return False
            except Exception as e:
                logger.error(f"Error adding column: {e}")
                return False
        
    except Exception as e:
        logger.error(f"Error connecting to database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("Adding missing balance_updated column to pending_deposits table")
    result = add_balance_updated_column()
    if result:
        logger.info("✅ Column added successfully")
        sys.exit(0)
    else:
        logger.error("❌ Failed to add column")
        sys.exit(1)

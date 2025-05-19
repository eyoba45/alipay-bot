"""
Database Migration Script

This script safely applies schema changes to your Neon PostgreSQL database.
It uses SQLAlchemy's inspection capabilities to check existing columns
and add missing ones without dropping any tables or data.
"""

import os
import logging
import sys
import traceback
import time
from sqlalchemy import Column, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from models import Base

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    logger.error("DATABASE_URL environment variable is not set!")
    sys.exit(1)

def get_engine():
    """Create a database engine with optimized settings"""
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_size=3,
            max_overflow=5,
            pool_timeout=30,
            pool_recycle=60,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 15,
                "application_name": "alipay_eth_db_migration",
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
                "sslmode": "require"
            }
        )
        logger.info("✅ Database engine created successfully")
        return engine
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)

def get_table_columns(engine, table_name):
    """Get existing columns for a table"""
    inspector = inspect(engine)
    columns = inspector.get_columns(table_name)
    return {column['name'] for column in columns}

def execute_sql(engine, sql, params=None):
    """Execute SQL with retry logic"""
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                if params:
                    conn.execute(text(sql), params)
                else:
                    conn.execute(text(sql))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error executing SQL (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.error(traceback.format_exc())
                return False
    return False

def add_column_if_missing(engine, table_name, column_name, column_type):
    """Add a column to a table if it doesn't exist"""
    try:
        columns = get_table_columns(engine, table_name)
        
        if column_name not in columns:
            logger.info(f"Adding missing column '{column_name}' to table '{table_name}'")
            sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            if execute_sql(engine, sql):
                logger.info(f"✅ Added column '{column_name}' to '{table_name}' successfully")
                return True
            else:
                logger.error(f"❌ Failed to add column '{column_name}' to '{table_name}'")
                return False
        else:
            logger.info(f"Column '{column_name}' already exists in '{table_name}'")
            return True
    except Exception as e:
        logger.error(f"Error checking/adding column '{column_name}': {e}")
        logger.error(traceback.format_exc())
        return False

def migrate_db():
    """Apply all pending migrations to the database"""
    engine = get_engine()
    
    # Check database connection
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).fetchone()
            if result and result[0] == 1:
                logger.info("✅ Database connection verified")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
        logger.error(traceback.format_exc())
        return False
    
    # List all migrations here
    migrations = [
        # Add columns to users table
        ('users', 'email', 'TEXT'),
        ('users', 'is_verified', 'BOOLEAN DEFAULT FALSE'),
        ('users', 'registration_complete', 'BOOLEAN DEFAULT TRUE'),
        
        # Add columns to orders table
        ('orders', 'tracking_number', 'TEXT'),
        ('orders', 'delivery_status', 'TEXT DEFAULT \'pending\''),
        ('orders', 'estimated_delivery', 'TIMESTAMP'),
        
        # Add columns to pending_deposits table if not added by add_balance_updated_column.py
        ('pending_deposits', 'verification_attempts', 'INTEGER DEFAULT 0'),
        ('pending_deposits', 'last_verified', 'TIMESTAMP'),
        
        # Add your other migrations here
    ]
    
    # Apply all migrations
    success_count = 0
    for table_name, column_name, column_type in migrations:
        if add_column_if_missing(engine, table_name, column_name, column_type):
            success_count += 1
    
    if migrations:
        logger.info(f"✅ Applied {success_count}/{len(migrations)} migrations successfully")
    else:
        logger.info("ℹ️ No migrations were specified to apply")
    
    return True

if __name__ == "__main__":
    logger.info("Starting database migration...")
    if migrate_db():
        logger.info("✅ Database migration completed successfully")
    else:
        logger.error("❌ Database migration failed")
        sys.exit(1)

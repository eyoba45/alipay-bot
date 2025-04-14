"""
Update Database Schema Script

This script updates the PostgreSQL database schema to add new tables 
or columns without losing existing data. It specifically adds the 
referral system related tables and columns.
"""

import os
import sys
import logging
import traceback
from sqlalchemy import text, inspect, Column, Integer, String, Float, DateTime, BigInteger, ForeignKey, Text, Boolean
from sqlalchemy.exc import SQLAlchemyError, ProgrammingError
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine

from models import Base, User, Referral, ReferralReward, UserBalance, Transaction
from database import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

def get_engine():
    """Create database engine with proper configuration"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    # Configure connection pooling for better performance
    return create_engine(
        database_url,
        pool_size=10,
        max_overflow=20,
        pool_recycle=300,
        pool_pre_ping=True
    )

def get_session():
    """Get a new database session"""
    engine = get_engine()
    session_factory = sessionmaker(bind=engine)
    Session = scoped_session(session_factory)
    return Session()

def check_table_exists(engine, table_name):
    """Check if a table exists in the database"""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()

def check_column_exists(engine, table_name, column_name):
    """Check if a column exists in a table"""
    inspector = inspect(engine)
    columns = [c["name"] for c in inspector.get_columns(table_name)]
    return column_name in columns

def add_column(engine, table_name, column):
    """Add a column to an existing table"""
    column_name = column.name
    column_type = column.type.compile(engine.dialect)
    
    # Handle nullable and default
    nullable = "" if column.nullable else "NOT NULL"
    default = f"DEFAULT {column.default.arg}" if column.default is not None and column.default.is_scalar else ""
    
    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} {nullable} {default}".strip()
    
    try:
        with engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        logger.info(f"Added column {column_name} to table {table_name}")
        return True
    except SQLAlchemyError as e:
        logger.error(f"Error adding column {column_name} to table {table_name}: {e}")
        return False

def update_user_table(engine):
    """Update the users table with referral-related columns"""
    if not check_table_exists(engine, 'users'):
        logger.error("Users table doesn't exist")
        return False
    
    columns_to_add = {
        'referral_code': Column('referral_code', String, unique=True, nullable=True),
        'referred_by_id': Column('referred_by_id', Integer, ForeignKey('users.id'), nullable=True),
        'referral_points': Column('referral_points', Integer, default=0),
    }
    
    success = True
    for column_name, column in columns_to_add.items():
        if not check_column_exists(engine, 'users', column_name):
            if not add_column(engine, 'users', column):
                success = False
        else:
            logger.info(f"Column {column_name} already exists in users table")
    
    return success

def create_missing_tables(engine):
    """Create any missing tables from our models"""
    # Dictionary of table names to their model classes
    tables = {
        'referrals': Referral,
        'referral_rewards': ReferralReward,
        'user_balances': UserBalance,
        'transactions': Transaction
    }
    
    # Create each table if it doesn't exist
    for table_name, model_class in tables.items():
        if not check_table_exists(engine, table_name):
            try:
                model_class.__table__.create(engine)
                logger.info(f"Created table {table_name}")
            except SQLAlchemyError as e:
                logger.error(f"Error creating table {table_name}: {e}")
        else:
            logger.info(f"Table {table_name} already exists")

def update_schema():
    """Main function to update the database schema"""
    try:
        logger.info("Starting database schema update")
        engine = get_engine()
        
        # Update users table with new columns
        if update_user_table(engine):
            logger.info("Successfully updated users table with referral columns")
        else:
            logger.warning("Some issues occurred updating the users table")
        
        # Create any missing tables
        create_missing_tables(engine)
        
        logger.info("Schema update completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Error updating schema: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    print("Updating database schema...")
    success = update_schema()
    if success:
        print("✅ Database schema updated successfully!")
    else:
        print("❌ Failed to update database schema. Check logs for details.")
        sys.exit(1)

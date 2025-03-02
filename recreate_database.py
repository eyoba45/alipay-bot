import os
import logging
import sys
from sqlalchemy import create_engine, text
from database import Base, engine
from models import User, Order

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def recreate_tables():
    """Drop all tables and recreate them"""
    try:
        # Drop all tables
        logger.info("Dropping all existing tables...")
        Base.metadata.drop_all(engine)
        logger.info("All tables dropped successfully")

        # Create all tables
        logger.info("Creating all tables with correct schema...")
        Base.metadata.create_all(engine)
        logger.info("All tables have been recreated successfully!")
        print("✅ Database tables recreated successfully!")

    except Exception as e:
        logger.error(f"Error recreating tables: {e}")
        print(f"❌ Error recreating database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    recreate_tables()
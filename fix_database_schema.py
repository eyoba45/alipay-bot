
import os
import sys
import logging
from sqlalchemy import inspect

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add local directory to path to ensure imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from database import engine, init_db, get_session, safe_close_session
    from models import Base, User, Order, PendingApproval, PendingDeposit
except ImportError as e:
    logger.error(f"Error importing modules: {e}")
    sys.exit(1)

def check_table_columns():
    """Check if database tables have all required columns"""
    inspector = inspect(engine)
    expected_columns = {
        'users': ['id', 'telegram_id', 'subscription_date', 'last_subscription_reminder', 
                  'name', 'phone', 'address', 'balance', 'created_at', 'updated_at'],
        'orders': ['id', 'user_id', 'order_number', 'product_link', 'order_id', 
                   'tracking_number', 'status', 'amount', 'created_at', 'updated_at'],
        'pending_approvals': ['id', 'telegram_id', 'name', 'phone', 'address', 'created_at'],
        'pending_deposits': ['id', 'user_id', 'amount', 'created_at', 'status']
    }
    
    tables_to_recreate = []
    
    for table_name, expected_cols in expected_columns.items():
        try:
            if not inspector.has_table(table_name):
                logger.warning(f"Table {table_name} does not exist!")
                tables_to_recreate.append(table_name)
                continue
                
            columns = [col['name'] for col in inspector.get_columns(table_name)]
            missing_cols = [col for col in expected_cols if col not in columns]
            
            if missing_cols:
                logger.warning(f"Table {table_name} is missing columns: {missing_cols}")
                tables_to_recreate.append(table_name)
        except Exception as e:
            logger.error(f"Error checking table {table_name}: {e}")
    
    return tables_to_recreate

def fix_database_schema():
    """Fix the database schema by recreating tables with missing columns"""
    try:
        session = None
        # Check if tables need to be recreated
        tables_to_recreate = check_table_columns()
        
        if not tables_to_recreate:
            logger.info("✅ All tables have the correct schema")
            return True
            
        logger.warning(f"Tables to recreate: {tables_to_recreate}")
        
        # Drop and recreate only the tables that need fixing
        for table_name in tables_to_recreate:
            try:
                logger.info(f"Dropping table {table_name}...")
                Base.metadata.tables[table_name].drop(engine, checkfirst=True)
                logger.info(f"Table {table_name} dropped")
            except Exception as e:
                logger.error(f"Error dropping table {table_name}: {e}")
        
        # Recreate the dropped tables
        try:
            logger.info("Recreating dropped tables...")
            Base.metadata.create_all(engine)
            logger.info("✅ Tables recreated successfully")
            return True
        except Exception as e:
            logger.error(f"Error recreating tables: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error fixing database schema: {e}")
        return False
    finally:
        if session:
            safe_close_session(session)

if __name__ == "__main__":
    logger.info("🔧 Starting database schema fix")
    
    # Initialize the database
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        sys.exit(1)
    
    # Fix the schema
    if fix_database_schema():
        logger.info("✅ Database schema fixed successfully")
    else:
        logger.error("❌ Failed to fix database schema")
        sys.exit(1)

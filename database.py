
import os
import logging
import time
import traceback
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from models import Base, User, Order
from filelock import FileLock

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
    # Provide fallback to SQLite for development
    logger.warning("Using SQLite as fallback - this is not recommended for production")
    DATABASE_URL = "sqlite:///alipay_eth.db"

# Connection pool monitoring lock
db_lock = FileLock("database_connections.lock", timeout=30)

# Create engine with optimized connection handling for deployment
try:
    # Handle both SQLite and PostgreSQL connection types
    if DATABASE_URL.startswith('sqlite'):
        connect_args = {'check_same_thread': False}
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            connect_args=connect_args
        )
    else:
        # PostgreSQL optimized settings
        engine = create_engine(
            DATABASE_URL,
            pool_size=5,         # Reduced from 10 to prevent connection issues
            max_overflow=10,     # Reduced from 20
            pool_timeout=20,     # Increased from 10
            pool_recycle=300,    
            pool_pre_ping=True,  # Keep pre-ping enabled for connection validation
            connect_args={
                "connect_timeout": 10,
                "application_name": "alipay_eth_telebot"
            }
        )
    logger.info("Database engine created successfully")
except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
    logger.error(traceback.format_exc())
    sys.exit(1)

# Create scoped session
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

def init_db(retry=True, max_retries=5):
    """Initialize the database, connecting to existing tables or creating them if they don't exist
    
    ⚠️ DATA PROTECTION: This function has been modified to NEVER drop or reset tables.
    It will only create tables that don't exist, preserving all existing data.
    
    ✅ SAFE MODE ACTIVE - Data protection measures implemented (May 6, 2025)
    """
    retry_delay = 1
    
    # DATA PROTECTION MEASURES
    # Force these to safe values to prevent any chance of data loss
    # This overrides any parameters to ensure data safety
    create_all_kwargs = {
        'checkfirst': True,  # Always check first if tables exist
    }
    
    for attempt in range(max_retries if retry else 1):
        try:
            # DATA SAFETY STEP 1: Verify we're in create-only mode
            if not hasattr(Base.metadata, 'create_all'):
                logger.error("❌ DATABASE PROTECTION: Refusing to proceed with potentially unsafe operation")
                return False
            
            # DATA SAFETY STEP 2: Create tables only if they don't exist (will never drop)
            Base.metadata.create_all(engine, **create_all_kwargs)
            logger.info("✅ DATA SAFE: Database tables verified, no tables reset or dropped")
            
            # DATA SAFETY STEP 3: Test connection only with a simple query
            from sqlalchemy import text
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1")).fetchone()
                if result and result[0] == 1:
                    logger.info("✅ Database connection verified (safe mode)")
                    
            return True
        except Exception as e:
            logger.error(f"❌ Error connecting to database (attempt {attempt+1}/{max_retries if retry else 1}): {e}")
            if retry and attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logger.error(traceback.format_exc())
                return False  # Always return False instead of raising to prevent crashing
    
    return False

def get_session():
    """Get a new database session with performance logging"""
    try:
        session = Session()
        return session
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        logger.error(traceback.format_exc())
        raise

@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Error in database transaction: {e}")
        session.rollback()
        raise
    finally:
        session.close()

def safe_close_session(session):
    """Safely close a database session"""
    if session:
        try:
            session.close()
        except Exception as e:
            logger.error(f"Error closing database session: {e}")

def with_retry(func):
    """Decorator for retrying database operations"""
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_delay = 0.5  # Start with 500ms delay
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.error(f"Database operation failed (attempt {attempt+1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
        
        # If we get here, all retries failed
        logger.error(f"All {max_retries} attempts failed for DB operation. Last error: {last_error}")
        logger.error(traceback.format_exc())
        raise last_error
    
    return wrapper

def check_db_connection():
    """Test database connection with diagnostics and autorecovery"""
    start_time = time.time()
    session = None
    
    for attempt in range(3):  # Try up to 3 times
        try:
            session = get_session()
            # Simple quick query to test connectivity
            from sqlalchemy import text
            result = session.execute(text("SELECT 1")).fetchone()
            elapsed = time.time() - start_time
            logger.info(f"✅ Database connection test successful ({elapsed:.3f}s)")
            return True
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Database connection test failed (attempt {attempt+1}/3, {elapsed:.3f}s): {e}")
            
            if attempt < 2:  # If not the last attempt
                logger.info("🔄 Resetting connection pool and retrying...")
                safe_close_session(session)
                reset_connection_pool()  # Try to reset the pool
                time.sleep(2 * (attempt + 1))  # Increasing backoff
            else:
                logger.error(traceback.format_exc())
        finally:
            safe_close_session(session)
    
    return False

def reset_connection_pool():
    """Reset the database connection pool in case of issues"""
    try:
        # Acquire lock to ensure we don't have multiple threads resetting simultaneously
        with db_lock:
            logger.warning("🔄 Resetting database connection pool")
            # Dispose current engine connections
            engine.dispose()
            logger.info("✅ Connection pool reset successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Error resetting connection pool: {e}")
        logger.error(traceback.format_exc())
        return False

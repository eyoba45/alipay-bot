
import os
import logging
import time
import traceback
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from models import Base, User, Order
from filelock import FileLock

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set!")

# Connection pool monitoring lock
db_lock = FileLock("database_connections.lock")

# Create engine with optimized connection handling for deployment
engine = create_engine(
    DATABASE_URL,
    pool_size=20,        # Increased for better concurrency
    max_overflow=30,     # Increased overflow for high traffic periods
    pool_timeout=3,      # Reduced timeout for faster error detection
    pool_recycle=30,     # More aggressive recycling to prevent stale connections
    pool_pre_ping=True,  # Keep pre-ping enabled for connection validation
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 15,  # Reduced idle time for more responsive connections
        "keepalives_interval": 5,  # More frequent keepalive checks
        "keepalives_count": 5,
        "connect_timeout": 3,  # Faster connection timeout
        "application_name": "alipay_eth_telebot",
        "sslmode": "require"  # Keep SSL mode enabled
    }
)

# Create scoped session
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

def init_db():
    """Initialize the database, creating all tables with retry logic"""
    max_retries = 5
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            Base.metadata.create_all(engine)
            logger.info("✅ Database tables created successfully")
            return
        except Exception as e:
            logger.error(f"❌ Error creating database tables (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                raise

def get_session():
    """Get a new database session with performance logging"""
    session = Session()
    return session

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
    try:
        if session:
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
    """Test database connection with diagnostics"""
    start_time = time.time()
    session = None
    try:
        session = get_session()
        # Simple quick query to test connectivity
        result = session.execute("SELECT 1").fetchone()
        elapsed = time.time() - start_time
        logger.info(f"✅ Database connection test successful ({elapsed:.3f}s)")
        return True
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"❌ Database connection test failed ({elapsed:.3f}s): {e}")
        logger.error(traceback.format_exc())
        return False
    finally:
        safe_close_session(session)

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

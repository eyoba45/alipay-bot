import os
import logging
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from contextlib import contextmanager
from models import Base, User, Order

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set!")

# Create engine with optimized connection handling for deployment
engine = create_engine(
    DATABASE_URL,
    pool_size=10,  # Reduced for deployment stability
    max_overflow=20,  # Reduced overflow
    pool_timeout=5,  # Slightly increased for more patience
    pool_recycle=60,  # More aggressive recycling for deployment
    pool_pre_ping=True,
    connect_args={
        "keepalives": 1,
        "keepalives_idle": 30,  
        "keepalives_interval": 10,
        "keepalives_count": 5,
        "connect_timeout": 5,
        "application_name": "alipay_eth_telebot"  # Helps identify connections
    }
)

# Create scoped session
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

def init_db():
    """Initialize the database, creating all tables"""
    try:
        Base.metadata.create_all(engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
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
#!/usr/bin/env python3
"""
Database Connection Pool Manager
Enhanced connection management for high-traffic environments
"""
import os
import logging
import time
import threading
import traceback
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from filelock import FileLock

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manages database connections with intelligent pooling and recovery"""
    
    def __init__(self, url=None, max_pool_size=20, max_overflow=30, pool_timeout=30, pool_recycle=300):
        self.url = url or os.environ.get('DATABASE_URL')
        if not self.url:
            raise ValueError("Database URL not provided and DATABASE_URL environment variable not set")
            
        self.max_pool_size = max_pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        
        # Connection monitoring
        self.connection_lock = FileLock("database_connections.lock", timeout=10)
        self.session_count = 0
        self.session_count_lock = threading.Lock()
        self.last_error_time = None
        self.error_count = 0
        self.last_reset_time = time.time()
        
        # Create engine with optimized settings
        self._create_engine()
        
        # Start monitoring thread
        self.monitoring_thread = threading.Thread(
            target=self._monitor_connections,
            name="DB-Connection-Monitor",
            daemon=True
        )
        self.monitoring_thread.start()
        
        logger.info(f"ConnectionManager initialized with pool_size={max_pool_size}, max_overflow={max_overflow}")
    
    def _create_engine(self):
        """Create the SQLAlchemy engine with optimized settings"""
        try:
            if self.url is None:
                raise ValueError("Database URL is None")
                
            if self.url.startswith('sqlite'):
                # SQLite settings
                connect_args = {'check_same_thread': False}
                self.engine = create_engine(
                    self.url,
                    pool_pre_ping=True,
                    connect_args=connect_args
                )
            else:
                # PostgreSQL optimized settings
                self.engine = create_engine(
                    self.url,
                    poolclass=QueuePool,
                    pool_size=self.max_pool_size,
                    max_overflow=self.max_overflow,
                    pool_timeout=self.pool_timeout,
                    pool_recycle=self.pool_recycle,
                    pool_pre_ping=True,
                    connect_args={
                        "connect_timeout": 10,
                        "application_name": "alipay_eth_telebot"
                    }
                )
                
            # Create session factory
            self.session_factory = sessionmaker(bind=self.engine)
            self.Session = scoped_session(self.session_factory)
            
            logger.info("✅ Database engine created successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to create database engine: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def get_session(self):
        """Get a database session with monitoring"""
        try:
            with self.session_count_lock:
                self.session_count += 1
                
            session = self.Session()
            return session
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            logger.error(traceback.format_exc())
            
            # Track error for possible recovery
            self.last_error_time = time.time()
            self.error_count += 1
            
            # If we're getting too many errors, reset the pool
            if self.error_count >= 5 and (time.time() - self.last_reset_time) > 60:
                self.reset_pool()
                
            raise
    
    def close_session(self, session):
        """Safely close a database session"""
        if session:
            try:
                session.close()
                with self.session_count_lock:
                    self.session_count -= 1
            except Exception as e:
                logger.error(f"Error closing database session: {e}")
    
    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations"""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception as e:
            logger.error(f"Error in database transaction: {e}")
            session.rollback()
            raise
        finally:
            self.close_session(session)
    
    def reset_pool(self):
        """Reset the connection pool in case of issues"""
        try:
            # Acquire lock to ensure we don't have multiple threads resetting simultaneously
            with self.connection_lock:
                logger.warning("🔄 Resetting database connection pool")
                
                # Get current engine statistics
                pool = self.engine.pool
                checkedin = pool.checkedin()
                checkedout = pool.checkedout()
                size = pool.size()
                
                logger.info(f"Pool stats before reset: checked_in={checkedin}, checked_out={checkedout}, size={size}")
                
                # Dispose current engine connections
                self.engine.dispose()
                
                # Reset session factory
                self.Session.remove()
                
                # Wait a moment for connections to be fully disposed
                time.sleep(1)
                
                # Create new engine
                self._create_engine()
                
                # Reset counters
                self.error_count = 0
                self.last_reset_time = time.time()
                
                logger.info("✅ Connection pool reset successfully")
                
            return True
        except Exception as e:
            logger.error(f"❌ Error resetting connection pool: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _monitor_connections(self):
        """Monitor database connections and perform maintenance"""
        while True:
            try:
                # Sleep for a while
                time.sleep(60)
                
                # Check if we need to perform maintenance
                with self.session_count_lock:
                    current_count = self.session_count
                
                # Get pool statistics
                try:
                    pool = self.engine.pool
                    checkedin = pool.checkedin()
                    checkedout = pool.checkedout()
                    size = pool.size()
                    
                    logger.info(f"DB Pool Stats: sessions={current_count}, checked_in={checkedin}, checked_out={checkedout}, size={size}")
                    
                    # Check for leaks (more sessions tracked than checked out)
                    if current_count > checkedout + 2:  # Allow some margin
                        logger.warning(f"Possible session leak detected: {current_count} active sessions but only {checkedout} checked out")
                    
                    # If we have a lot of connections but few are being used, consider resetting
                    if size > (self.max_pool_size * 0.8) and checkedout < (self.max_pool_size * 0.2) and (time.time() - self.last_reset_time) > 3600:
                        logger.info("Pool maintenance: Large pool with low usage, performing reset")
                        self.reset_pool()
                        
                except Exception as pool_err:
                    logger.error(f"Error checking pool stats: {pool_err}")
                
            except Exception as e:
                logger.error(f"Error in connection monitoring: {e}")
    
    def check_connection(self):
        """Test the database connection"""
        session = None
        start_time = time.time()
        
        try:
            session = self.get_session()
            # Simple quick query to test connectivity
            from sqlalchemy import text
            result = session.execute(text("SELECT 1")).fetchone()
            elapsed = time.time() - start_time
            logger.info(f"✅ Database connection test successful ({elapsed:.3f}s)")
            return True
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Database connection test failed ({elapsed:.3f}s): {e}")
            logger.error(traceback.format_exc())
            return False
        finally:
            if session:
                self.close_session(session)
    
# Create global instance
connection_manager = ConnectionManager()

# Provide compatibility functions for easy migration from old code
def get_session():
    """Get a database session (compatibility function)"""
    return connection_manager.get_session()

def safe_close_session(session):
    """Safely close a database session (compatibility function)"""
    return connection_manager.close_session(session)

@contextmanager
def session_scope():
    """Provide a transactional scope (compatibility function)"""
    with connection_manager.session_scope() as session:
        yield session

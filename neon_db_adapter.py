#!/usr/bin/env python3
"""
Neon PostgreSQL Database Adapter

Special handling for Neon PostgreSQL serverless database service
to manage rate limiting and connection scaling.
"""
import os
import time
import random
import logging
import threading
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import OperationalError, InterfaceError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NeonDatabaseAdapter:
    """
    Special adapter for Neon PostgreSQL connections
    that handles rate limiting and backoff
    """
    def __init__(self, url=None, app_name="alipay_eth_telebot"):
        self.url = url or os.environ.get('DATABASE_URL')
        if not self.url:
            raise ValueError("Database URL not provided and DATABASE_URL environment variable not set")
            
        self.app_name = app_name
        
        # Connection management with extreme caution
        self.connection_count = 0
        self.connection_lock = threading.RLock()
        self.last_connection_time = datetime.now() - timedelta(minutes=1)
        self.min_connection_interval = 1.0  # Increased to 1 second between connections
        
        # Rate limit tracking with circuit breaker pattern
        self.rate_limit_hit = False
        self.last_rate_limit = None
        self.backoff_time = 1.0  # initial backoff in seconds
        self.max_backoff = 120.0  # increased maximum backoff to 2 minutes
        self.backoff_factor = 2.5  # more aggressive backoff multiplier
        self.consecutive_failures = 0
        
        # Circuit breaker for extreme rate limiting
        self.circuit_open = False  # Circuit breaker status
        self.circuit_open_time = None  # When circuit was opened
        self.circuit_recovery_time = 300  # 5 minutes recovery when circuit opens
        
        # Create minimal connection pool
        self._create_engine()
        
        # Monitor thread
        self.monitor_thread = threading.Thread(
            target=self._monitor_connections,
            daemon=True,
            name="NeonDB-Monitor"
        )
        self.monitor_thread.start()
        
        logger.info(f"Neon Database Adapter initialized for {app_name}")
        
    def _create_engine(self):
        """Create a minimal SQLAlchemy engine with conservative settings"""
        try:
            # Very conservative pool settings for Neon
            engine_url = str(self.url)  # Ensure URL is a string
            self.engine = create_engine(
                engine_url,
                pool_size=3,           # Small pool
                max_overflow=2,        # Minimal overflow
                pool_timeout=10,       # Wait time for connection
                pool_recycle=60,       # Recycle old connections
                pool_pre_ping=True,    # Check connection before using
                connect_args={
                    "connect_timeout": 15,    # Longer timeout for connection
                    "application_name": self.app_name,
                    "options": "-c statement_timeout=15000"  # 15s statement timeout
                }
            )
            
            # Create session factory with minimal session
            self.session_factory = sessionmaker(
                bind=self.engine,
                expire_on_commit=False  # Don't expire objects after commit
            )
            self.Session = scoped_session(self.session_factory)
            
            logger.info("✅ Neon database engine created with minimal connection pool")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to create Neon database engine: {e}")
            return False
            
    def get_session(self):
        """Get a database session with rate limit protection and circuit breaker"""
        with self.connection_lock:
            # Check circuit breaker - completely block requests if open
            if self.circuit_open:
                now = datetime.now()
                if self.circuit_open_time and (now - self.circuit_open_time).total_seconds() < self.circuit_recovery_time:
                    # Circuit still open - block all requests
                    recovery_time = self.circuit_recovery_time - (now - self.circuit_open_time).total_seconds()
                    logger.warning(f"🔌 Circuit breaker open - blocking all DB connections for {recovery_time:.1f}s more")
                    raise OperationalError("Circuit breaker open - database connections blocked temporarily")
                else:
                    # Reset circuit breaker - allow a test request
                    logger.info("🔌 Circuit breaker reset after recovery period")
                    self.circuit_open = False
                    self.circuit_open_time = None
            
            # Check if we need to apply backoff due to rate limiting
            if self.rate_limit_hit:
                now = datetime.now()
                if self.last_rate_limit and (now - self.last_rate_limit).total_seconds() < self.backoff_time:
                    sleep_time = self.backoff_time - (now - self.last_rate_limit).total_seconds()
                    if sleep_time > 0:
                        logger.info(f"⏱️ Rate limit backoff, sleeping for {sleep_time:.2f}s")
                        time.sleep(sleep_time)
            
            # Apply minimum interval between connections (much higher now to handle severe rate limiting)
            now = datetime.now()
            time_since_last = (now - self.last_connection_time).total_seconds()
            min_interval = self.min_connection_interval
            
            # Add progressive slowdown based on failures
            if self.consecutive_failures > 0:
                # Progressively increase interval based on failure count
                min_interval = min_interval * (1 + self.consecutive_failures)
                
            if time_since_last < min_interval:
                sleep_time = min_interval - time_since_last
                # Add jitter to prevent synchronized requests
                sleep_time *= random.uniform(1.0, 1.5)
                time.sleep(sleep_time)
                
            # Update last connection time
            self.last_connection_time = datetime.now()
            
        try:
            session = self.Session()
            with self.connection_lock:
                self.connection_count += 1
                self.consecutive_failures = 0  # Reset on success
            return session
        except OperationalError as e:
            error_str = str(e).lower()
            
            # Various error phrases that indicate rate limiting issues
            rate_limit_phrases = [
                "rate limit", 
                "too many connections", 
                "too many database connection attempts",
                "failed to acquire permit", 
                "control plane request failed"
            ]
            
            is_rate_limited = any(phrase in error_str for phrase in rate_limit_phrases)
            
            if is_rate_limited:
                with self.connection_lock:
                    self.rate_limit_hit = True
                    self.last_rate_limit = datetime.now()
                    self.consecutive_failures += 1
                    
                    # Apply exponential backoff with jitter
                    self.backoff_time = min(
                        self.backoff_time * self.backoff_factor,
                        self.max_backoff
                    )
                    # Add randomness to avoid thundering herd
                    jitter = random.uniform(0.75, 1.25)
                    effective_backoff = self.backoff_time * jitter
                    
                    logger.warning(f"⚠️ Neon rate limit hit. Backoff set to {effective_backoff:.2f}s (consecutive: {self.consecutive_failures})")
                    
                    # For severe rate limiting, open the circuit breaker to stop all traffic
                    if self.consecutive_failures >= 5:
                        self.circuit_open = True
                        self.circuit_open_time = datetime.now()
                        logger.critical(f"🔌 Circuit breaker OPEN - blocking all database connections for {self.circuit_recovery_time}s due to severe rate limiting")
                    # If we've had too many consecutive failures, slow down more aggressively
                    elif self.consecutive_failures >= 3:
                        logger.warning(f"🛑 Multiple consecutive rate limits ({self.consecutive_failures}), applying extended backoff")
                        time.sleep(effective_backoff)
                        
            raise
            
    def close_session(self, session):
        """Close a database session"""
        if session:
            try:
                session.close()
                with self.connection_lock:
                    self.connection_count = max(0, self.connection_count - 1)
            except Exception as e:
                logger.error(f"Error closing session: {e}")
                
    def _monitor_connections(self):
        """Monitor connection status and rate limiting"""
        while True:
            try:
                time.sleep(60)  # Check every minute
                
                with self.connection_lock:
                    # If we've successfully connected recently, gradually reduce backoff
                    if (not self.rate_limit_hit or 
                        (self.last_rate_limit and 
                         (datetime.now() - self.last_rate_limit).total_seconds() > 60)):
                        self.backoff_time = max(1.0, self.backoff_time * 0.8)
                        
                        # If it's been a while since rate limiting, reset completely
                        if (self.last_rate_limit and 
                            (datetime.now() - self.last_rate_limit).total_seconds() > 300):
                            self.rate_limit_hit = False
                            self.backoff_time = 1.0
                            logger.info("✅ Neon rate limit state reset after recovery period")
                            
                    # Log current status
                    if self.rate_limit_hit:
                        logger.info(f"Neon connection status: {self.connection_count} active, " +
                                  f"rate limited with {self.backoff_time:.2f}s backoff, " +
                                  f"{self.consecutive_failures} consecutive failures")
                    else:
                        logger.info(f"Neon connection status: {self.connection_count} active connections")
            except Exception as e:
                logger.error(f"Error in Neon connection monitor: {e}")
                
    def check_connection(self):
        """Test database connection with backoff"""
        session = None
        start_time = time.time()  # Define start_time before usage
        try:
            session = self.get_session()
            
            # Simple test query
            result = session.execute(text("SELECT 1")).scalar()
            
            elapsed = time.time() - start_time
            logger.info(f"✅ Neon database connection test successful ({elapsed:.2f}s)")
            return True
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"❌ Neon database connection test failed ({elapsed:.2f}s): {e}")
            return False
        finally:
            if session:
                self.close_session(session)
                
    def execute_query(self, query_func, max_retries=3):
        """
        Execute a database query with automatic retry and backoff
        
        Args:
            query_func: A function that takes a session as argument and performs queries
            max_retries: Maximum number of retry attempts
            
        Returns:
            The result of query_func or None on failure
        """
        retries = 0
        last_error = None
        
        while retries <= max_retries:
            session = None
            try:
                session = self.get_session()
                result = query_func(session)
                return result
            except OperationalError as e:
                error_str = str(e).lower()
                retries += 1
                last_error = e
                
                if "rate limit" in error_str or "too many connections" in error_str:
                    # This is already handled in get_session with backoff
                    logger.warning(f"Neon rate limit error (attempt {retries}/{max_retries})")
                    # Wait additional time with jitter before retry
                    delay = min(2**retries, 10) * random.uniform(0.75, 1.25)
                    time.sleep(delay)
                else:
                    # For other operational errors
                    logger.error(f"Database error (attempt {retries}/{max_retries}): {e}")
                    delay = min(2**retries, 15)
                    time.sleep(delay)
            except Exception as e:
                logger.error(f"Unexpected error executing query: {e}")
                retries += 1
                last_error = e
                time.sleep(min(2**retries, 15))
            finally:
                if session:
                    self.close_session(session)
                    
        # If we get here, all retries failed
        if last_error:
            logger.error(f"Query failed after {max_retries} attempts: {last_error}")
        return None

# Create singleton instance
neon_db = NeonDatabaseAdapter()

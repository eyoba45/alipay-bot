#!/usr/bin/env python3
"""
Database Helper Functions for Rate-Limited Connections

This module provides helper functions for database operations
that are resilient to rate limiting issues with Neon PostgreSQL.
"""
import logging
import functools
import time
import random
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

# Import our Neon-specific database adapter
from neon_db_adapter import neon_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def with_neon_retry(max_retries=3, initial_delay=1, max_delay=30):
    """
    Decorator for functions that perform database operations
    to handle Neon rate limiting
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            delay = initial_delay
            
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    error_message = str(e).lower()
                    retries += 1
                    
                    # Check for rate limit errors
                    if ("rate limit" in error_message or 
                        "too many connections" in error_message or
                        "control plane request failed" in error_message):
                        
                        if retries <= max_retries:
                            # Calculate delay with exponential backoff and jitter
                            jitter = random.uniform(0.75, 1.25)
                            current_delay = min(delay * jitter, max_delay)
                            
                            logger.warning(f"Neon rate limit error in {func.__name__}, " +
                                          f"retrying ({retries}/{max_retries}) after {current_delay:.2f}s")
                            time.sleep(current_delay)
                            
                            # Increase delay for next attempt
                            delay = min(delay * 2, max_delay)
                        else:
                            logger.error(f"Neon rate limit error in {func.__name__} " +
                                        f"after {max_retries} retries: {e}")
                            raise
                    else:
                        # For non-rate limit errors
                        logger.error(f"Database error in {func.__name__}: {e}")
                        raise
                    
            # If we get here, all retries failed
            raise RuntimeError(f"Failed after {max_retries} retries in {func.__name__}")
            
        return wrapper
    return decorator

def execute_safe_query(query_func):
    """
    Execute a database query safely with retries for rate limiting
    
    Args:
        query_func: Function that takes a session parameter and performs DB operations
        
    Returns:
        Result of the query function or None on error
    """
    return neon_db.execute_query(query_func)

def check_db_status():
    """Check database connection status"""
    return neon_db.check_connection()

def get_database_metrics():
    """Get database connection metrics and health status"""
    try:
        metrics = {
            "connection_count": neon_db.connection_count,
            "rate_limited": neon_db.rate_limit_hit,
            "backoff_time": round(neon_db.backoff_time, 2),
            "consecutive_failures": neon_db.consecutive_failures,
            "timestamp": datetime.now().isoformat()
        }
        
        # Check database responsiveness with a simple query
        session = None
        try:
            session = neon_db.get_session()
            start_time = time.time()
            session.execute(text("SELECT 1")).scalar()
            
            metrics["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
            metrics["status"] = "online"
        except Exception as e:
            metrics["status"] = "error"
            metrics["error"] = str(e)
        finally:
            if session:
                neon_db.close_session(session)
                
        return metrics
    except Exception as e:
        logger.error(f"Error getting database metrics: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# Example usage:
# 
# @with_neon_retry(max_retries=3)
# def get_user(user_id):
#     session = neon_db.get_session()
#     try:
#         user = session.query(User).filter_by(id=user_id).first()
#         return user
#     finally:
#         neon_db.close_session(session)
#
# # Alternative approach using execute_safe_query:
# def get_user_data(user_id):
#     def query_func(session):
#         return session.query(User).filter_by(id=user_id).first()
#     
#     return execute_safe_query(query_func)

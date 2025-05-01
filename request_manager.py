#!/usr/bin/env python3
"""
Request Manager for Telegram Bot
Handles concurrent request management, rate limiting, and request recovery
"""
import time
import logging
import threading
import queue
import traceback
from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RequestManager:
    """Manager for handling concurrent requests with rate limiting"""
    
    def __init__(self, 
                 global_rate_limit=25,         # Max 25 requests per second globally
                 user_rate_limit=5,            # Max 5 requests per second per user
                 max_queue_size=1000,          # Maximum queue size
                 worker_count=5,               # Number of worker threads
                 recovery_timeout=10,          # Seconds to wait for recovery
                 max_retry_attempts=3):        # Maximum retry attempts
        
        self.global_rate_limit = global_rate_limit
        self.user_rate_limit = user_rate_limit
        self.max_queue_size = max_queue_size
        self.worker_count = worker_count
        self.recovery_timeout = recovery_timeout
        self.max_retry_attempts = max_retry_attempts
        
        # Request tracking
        self.request_queue = queue.Queue(maxsize=max_queue_size)
        self.user_requests = defaultdict(lambda: deque(maxlen=100))  # Track recent requests by user
        self.user_last_request = {}  # Last request time by user
        self.global_request_times = deque(maxlen=global_rate_limit * 2)  # Recent global requests
        
        # Workers
        self.workers = []
        self.running = False
        
        # Performance metrics
        self.processed_count = 0
        self.error_count = 0
        self.retry_count = 0
        self.start_time = None
        self.metrics_lock = threading.Lock()
        
        # Recovery tracking
        self.failing_handlers = defaultdict(int)  # Track handlers that are consistently failing
        self.recovery_mode = False
        self.recovery_start_time = None
        
    def start(self):
        """Start the request manager workers"""
        if self.running:
            return
            
        logger.info(f"Starting RequestManager with {self.worker_count} workers")
        self.running = True
        self.start_time = time.time()
        
        # Start worker threads
        for i in range(self.worker_count):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"RequestWorker-{i}",
                daemon=True
            )
            worker.start()
            self.workers.append(worker)
            
        # Start metrics reporting thread
        metrics_thread = threading.Thread(
            target=self._report_metrics,
            name="MetricsReporter",
            daemon=True
        )
        metrics_thread.start()
        
        logger.info("✅ RequestManager started successfully")
        
    def stop(self):
        """Stop the request manager"""
        if not self.running:
            return
            
        logger.info("Stopping RequestManager...")
        self.running = False
        
        # Wait for workers to finish
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=5)
                
        self.workers = []
        logger.info("✅ RequestManager stopped")
        
    def add_request(self, handler_func, *args, **kwargs):
        """
        Add a new request to the queue
        If the queue is full, the request will be rejected
        """
        if not self.running:
            logger.warning("RequestManager is not running, request rejected")
            return False
            
        # Get user ID for rate limiting (if available)
        user_id = None
        if args and hasattr(args[0], 'from_user') and hasattr(args[0].from_user, 'id'):
            user_id = args[0].from_user.id
        
        # Check user rate limit
        if user_id and self._check_user_rate_limit(user_id):
            # User is being rate limited
            logger.warning(f"Rate limiting user {user_id}, too many requests")
            return False
            
        # Check global rate limit
        if self._check_global_rate_limit():
            # Global rate limit reached
            logger.warning("Global rate limit reached, request queued")
            # We still queue the request, but it will be processed later
        
        try:
            # Package the request
            request = {
                'handler': handler_func,
                'args': args,
                'kwargs': kwargs,
                'user_id': user_id,
                'timestamp': time.time(),
                'attempts': 0
            }
            
            # Add to queue with timeout to prevent blocking
            self.request_queue.put(request, timeout=1)
            
            # Update user's last request time
            if user_id:
                now = time.time()
                self.user_last_request[user_id] = now
                self.user_requests[user_id].append(now)
                
            # Update global request times
            self.global_request_times.append(time.time())
            
            return True
        except queue.Full:
            logger.error("Request queue is full, request rejected")
            return False
        except Exception as e:
            logger.error(f"Error adding request to queue: {e}")
            return False
            
    def _worker_loop(self):
        """Worker thread to process requests from the queue"""
        logger.info(f"Worker {threading.current_thread().name} started")
        
        while self.running:
            try:
                # Get a request from the queue with timeout
                try:
                    request = self.request_queue.get(timeout=1)
                except queue.Empty:
                    continue
                    
                # Process the request
                try:
                    handler_func = request['handler']
                    args = request['args']
                    kwargs = request['kwargs']
                    
                    # Call the handler
                    handler_func(*args, **kwargs)
                    
                    # Successful processing
                    with self.metrics_lock:
                        self.processed_count += 1
                    
                    # Reset failure count for this handler
                    handler_name = handler_func.__name__
                    if handler_name in self.failing_handlers:
                        del self.failing_handlers[handler_name]
                        
                except Exception as e:
                    # Handle failure
                    with self.metrics_lock:
                        self.error_count += 1
                        
                    # Get handler name for tracking
                    handler_name = request['handler'].__name__
                    
                    # Log the error
                    logger.error(f"Error processing request ({handler_name}): {e}")
                    logger.error(traceback.format_exc())
                    
                    # Track failing handlers
                    self.failing_handlers[handler_name] += 1
                    
                    # Check if we should retry
                    if request['attempts'] < self.max_retry_attempts:
                        # Increment attempt count and requeue
                        request['attempts'] += 1
                        with self.metrics_lock:
                            self.retry_count += 1
                            
                        logger.info(f"Retrying request ({handler_name}), attempt {request['attempts']}/{self.max_retry_attempts}")
                        self.request_queue.put(request)
                    else:
                        logger.error(f"Request failed after {self.max_retry_attempts} attempts: {handler_name}")
                        
                    # Check if we should enter recovery mode
                    self._check_recovery_mode()
                    
                finally:
                    # Mark task as done
                    self.request_queue.task_done()
                    
            except Exception as e:
                logger.error(f"Worker error: {e}")
                logger.error(traceback.format_exc())
                
        logger.info(f"Worker {threading.current_thread().name} stopped")
                
    def _check_user_rate_limit(self, user_id):
        """
        Check if user has exceeded rate limit
        Returns True if rate limited, False otherwise
        """
        if user_id not in self.user_last_request:
            return False
            
        # Get recent requests for this user
        recent_requests = self.user_requests[user_id]
        if not recent_requests:
            return False
            
        # Check if user has made too many requests recently
        now = time.time()
        one_second_ago = now - 1
        
        # Count requests in the last second
        recent_count = sum(1 for req_time in recent_requests if req_time > one_second_ago)
        
        return recent_count >= self.user_rate_limit
        
    def _check_global_rate_limit(self):
        """
        Check if global rate limit has been reached
        Returns True if rate limited, False otherwise
        """
        if not self.global_request_times:
            return False
            
        # Check if we've hit the global rate limit
        now = time.time()
        one_second_ago = now - 1
        
        # Count global requests in the last second
        recent_count = sum(1 for req_time in self.global_request_times if req_time > one_second_ago)
        
        return recent_count >= self.global_rate_limit
        
    def _check_recovery_mode(self):
        """Check if we should enter recovery mode due to cascading failures"""
        # Check if too many handlers are failing
        failing_count = sum(1 for count in self.failing_handlers.values() if count >= 3)
        
        if failing_count >= 3 and not self.recovery_mode:
            # Enter recovery mode
            logger.warning("⚠️ Entering recovery mode due to cascading failures")
            self.recovery_mode = True
            self.recovery_start_time = time.time()
            
            # Slow down processing while in recovery
            time.sleep(self.recovery_timeout / 2)
        elif self.recovery_mode:
            # Check if we should exit recovery mode
            if self.recovery_start_time and time.time() - self.recovery_start_time > self.recovery_timeout:
                logger.info("✅ Exiting recovery mode")
                self.recovery_mode = False
                self.recovery_start_time = None
                self.failing_handlers.clear()
                
    def _report_metrics(self):
        """Periodically report metrics on request processing"""
        while self.running:
            try:
                time.sleep(60)  # Report every minute
                
                if not self.start_time:
                    continue
                    
                with self.metrics_lock:
                    uptime = time.time() - self.start_time
                    queue_size = self.request_queue.qsize()
                    processed = self.processed_count
                    errors = self.error_count
                    retries = self.retry_count
                    
                logger.info(f"RequestManager Metrics - "
                           f"Uptime: {int(uptime)}s, "
                           f"Queue: {queue_size}, "
                           f"Processed: {processed}, "
                           f"Errors: {errors}, "
                           f"Retries: {retries}, "
                           f"Rate: {processed/uptime:.1f}/s")
                           
            except Exception as e:
                logger.error(f"Error in metrics reporting: {e}")
                
        logger.info("Metrics reporting stopped")
        
# Create a global instance
request_manager = RequestManager()

def managed_request(func):
    """
    Decorator for adding a request to the manager
    Use this on all Telegram message handler functions
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Add to request manager instead of executing immediately
        request_manager.add_request(func, *args, **kwargs)
    return wrapper

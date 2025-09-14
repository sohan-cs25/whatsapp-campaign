# campaigns/rate_limiter.py

import time
import logging
from decouple import config
from django.core.cache import cache
from functools import wraps

logger = logging.getLogger(__name__)


class SimpleRateLimiter:
    """
    Simple rate limiter for WhatsApp API calls
    Uses Django's cache backend
    """
    
    def __init__(self, campaign_id=None):
        self.campaign_id = campaign_id or 'global'
        self.max_per_second = config('WHATSAPP_RATE_LIMIT_PER_SECOND', cast=int, default=10)
        self.max_per_minute = config('WHATSAPP_RATE_LIMIT_PER_MINUTE', cast=int, default=100)
        
    def can_send(self):
        """
        Check if we can send a message based on rate limits
        
        Returns:
            bool: True if we can send, False otherwise
        """
        current_time = time.time()
        
        # Check per-second limit
        second_key = f"rate_limit:second:{self.campaign_id}:{int(current_time)}"
        second_count = cache.get(second_key, 0)
        
        if second_count >= self.max_per_second:
            logger.warning(f"Rate limit hit: {second_count}/{self.max_per_second} per second")
            return False
        
        # Check per-minute limit
        minute = int(current_time / 60)
        minute_key = f"rate_limit:minute:{self.campaign_id}:{minute}"
        minute_count = cache.get(minute_key, 0)
        
        if minute_count >= self.max_per_minute:
            logger.warning(f"Rate limit hit: {minute_count}/{self.max_per_minute} per minute")
            return False
        
        # Increment counters
        cache.set(second_key, second_count + 1, timeout=2)  # Expire after 2 seconds
        cache.set(minute_key, minute_count + 1, timeout=62)  # Expire after 62 seconds
        
        return True
    
    def get_wait_time(self):
        """
        Get how long to wait before next send is allowed
        
        Returns:
            int: Seconds to wait
        """
        # Simple implementation: wait 1 second if rate limited
        return 1


def rate_limit_check(func):
    """
    Decorator to apply rate limiting to functions
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Try to get campaign_id from arguments
        campaign_id = kwargs.get('campaign_id')
        
        if campaign_id:
            limiter = SimpleRateLimiter(campaign_id)
            
            # Wait if rate limited
            max_attempts = 10
            attempts = 0
            
            while not limiter.can_send() and attempts < max_attempts:
                wait_time = limiter.get_wait_time()
                logger.info(f"Rate limited, waiting {wait_time} seconds...")
                time.sleep(wait_time)
                attempts += 1
            
            if attempts >= max_attempts:
                raise Exception(f"Rate limit exceeded after {max_attempts} attempts")
        
        return func(*args, **kwargs)
    
    return wrapper
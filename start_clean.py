
#!/usr/bin/env python3
"""
Clean start script for Telegram bot with proper initialization
"""
import os
import sys
import subprocess
import time
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

def main():
    """Clean start the bot with proper initialization"""
    logger.info("🧹 Starting cleanup...")
    try:
        # Run cleanup first
        subprocess.run([sys.executable, "clean_locks.py", "--force"], check=True)
        logger.info("✅ Cleanup completed")
        
        # Allow a moment for processes to fully terminate
        time.sleep(2)
        
        # Start the bot using run_bot.py (the most reliable launcher)
        logger.info("🚀 Starting bot...")
        subprocess.run([sys.executable, "run_bot.py"], check=True)
    except KeyboardInterrupt:
        logger.info("👋 Process terminated by user")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())

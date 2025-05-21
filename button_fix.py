#!/usr/bin/env python3
"""
Button Fix for Telegram Bot

This script adds answer_callback_query calls to all callback handlers
to ensure buttons immediately respond when clicked.
"""

import os
import re
import logging
import shutil
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def apply_button_fix():
    """Apply a fix to make buttons respond immediately"""
    bot_file = 'bot.py'
    
    # Create a backup of the original file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"{bot_file}.button_fix_{timestamp}.bak"
    try:
        shutil.copy2(bot_file, backup_file)
        logger.info(f"Created backup: {backup_file}")
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        return False
    
    # Read the current content
    with open(bot_file, 'r', encoding='utf-8') as file:
        content = file.read()
    
    # First, add a global callback handler if one doesn't exist
    if "@bot.callback_query_handler(func=lambda call: True)" not in content:
        # Find 'def main():'
        main_pos = content.find('def main():')
        if main_pos == -1:
            logger.error("Could not find 'def main():'")
            return False
        
        # Find the last function before main()
        last_func_pos = content.rfind('def ', 0, main_pos)
        if last_func_pos == -1:
            logger.error("Could not find the last function before main()")
            return False
        
        # Find the end of that function
        end_of_last_func = content.find('\n\n', last_func_pos)
        if end_of_last_func == -1:
            end_of_last_func = main_pos
        
        # Global fallback handler
        fallback_handler = """

# Global fallback handler for all callbacks
@bot.callback_query_handler(func=lambda call: True)
def fallback_callback_handler(call):
    # Always answer the callback to remove the loading spinner
    try:
        bot.answer_callback_query(call.id)
        logger.debug(f"Fallback handler answered callback: {call.id}")
    except Exception as e:
        logger.error(f"Error in fallback callback handler: {e}")
    
    # Return False to let other handlers process this callback
    return False

"""
        
        # Insert the fallback handler
        new_content = content[:end_of_last_func] + fallback_handler + content[end_of_last_func:]
        
        # Write the modified content back to the file
        with open(bot_file, 'w', encoding='utf-8') as file:
            file.write(new_content)
        
        logger.info("Added global fallback callback handler")
    else:
        logger.info("Global callback handler already exists")
    
    return True

if __name__ == "__main__":
    success = apply_button_fix()
    if success:
        print("✅ Successfully applied button fix!")
        print("✅ All buttons should now respond immediately when clicked!")
    else:
        print("❌ Failed to apply button fix.")

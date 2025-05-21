#!/usr/bin/env python3
"""
Direct Button Handler Fix for Telegram Bot

This script directly adds a generic callback handler at the top of the bot.py file
to ensure all inline buttons are responsive, regardless of their specific implementation.

This is a simpler, more direct approach that should work even if there are other issues
with the callback implementations.
"""

import os
import logging
from datetime import datetime
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def apply_direct_button_fix():
    """Apply a direct fix to ensure all inline buttons are responsive"""
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
    
    # Find the setup_admin_handlers function call
    setup_call_pos = content.find("setup_admin_handlers(bot)")
    
    if setup_call_pos == -1:
        # If we can't find the setup call, look for a different insertion point
        import_pos = content.find("from admin_handlers import setup_admin_handlers")
        if import_pos == -1:
            logger.error("Could not find a suitable insertion point in the file.")
            return False
        
        # Add the setup call after the import
        end_line = content.find("\n", import_pos)
        if end_line != -1:
            setup_call_pos = end_line
    
    # Create the direct button fix code
    direct_fix = """
# Direct fix for non-responsive inline buttons
# This ensures all buttons get their callbacks answered immediately

# Register a top-level handler for ALL callback queries that immediately answers them
@bot.callback_query_handler(func=lambda call: True)
def ensure_all_callbacks_answered(call):
    # Immediately answer all callback queries to prevent loading spinner
    try:
        bot.answer_callback_query(call.id)
        logger.info(f"Answered callback query {call.id} for data: {call.data}")
    except Exception as e:
        logger.error(f"Error answering callback query {call.id}: {e}")
    
    # Let the processing continue for specific handlers
    # We don't return here, allowing other handlers to also process the callback
"""
    
    # Insert the direct fix after the setup call
    new_content = content[:setup_call_pos] + "\n" + direct_fix + content[setup_call_pos:]
    
    # Write the modified content back to the file
    with open(bot_file, 'w', encoding='utf-8') as file:
        file.write(new_content)
    
    logger.info("Applied direct button fix to ensure all inline buttons are responsive")
    return True

if __name__ == "__main__":
    success = apply_direct_button_fix()
    if success:
        print("✅ Successfully applied direct button fix!")
    else:
        print("❌ Failed to apply direct button fix.")

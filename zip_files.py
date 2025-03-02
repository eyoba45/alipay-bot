import os
import zipfile
from datetime import datetime

def create_zip():
    # Get current timestamp for the zip file name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"alipay_eth_bot_{timestamp}.zip"
    
    # Create a zip file
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # List of files to include
        files_to_zip = [
            'bot.py',
            'monitor_bot.py',
            'clean_locks.py',
            'database.py',
            'models.py',
            'recreate_database.py',
            'test_bot.py',
            'test_startup.py',
            '.replit',
            'pyproject.toml',
            'replit.nix'
        ]
        
        # Add each file to the zip
        for file in files_to_zip:
            if os.path.exists(file):
                zipf.write(file)
                print(f"Added {file} to {zip_filename}")
    
    print(f"\n✅ Created zip file: {zip_filename}")
    print("You can now download this file from your Replit project files.")

if __name__ == "__main__":
    create_zip()

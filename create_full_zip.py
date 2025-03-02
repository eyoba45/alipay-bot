
import os
import zipfile
from datetime import datetime

def create_full_zip():
    # Get current timestamp for the zip file name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"alipay_bot_full_{timestamp}.zip"
    
    # Create a zip file
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Get all files in the current directory
        excluded_dirs = ['.git', '__pycache__', '.upm']
        excluded_files = [zip_filename]  # Don't include the zip file itself
        
        for root, dirs, files in os.walk('.'):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            
            for file in files:
                file_path = os.path.join(root, file)
                
                # Skip the zip file itself and any other excluded files
                if file in excluded_files or file.endswith('.zip'):
                    continue
                    
                # Add file to zip
                print(f"Adding: {file_path}")
                zipf.write(file_path)
    
    print(f"\n✅ Created full zip file: {zip_filename}")
    print(f"✅ ZIP file size: {os.path.getsize(zip_filename) / (1024*1024):.2f} MB")
    print("You can now download this file from your Replit project files.")

if __name__ == "__main__":
    create_full_zip()

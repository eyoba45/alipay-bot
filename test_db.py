
"""Test database connection"""
import os
import logging
import sys
from database import init_db, get_session, safe_close_session
from models import User

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_database():
    """Test if database connection is working"""
    try:
        print("Testing database connection...")
        session = None
        
        # Initialize the database
        init_db()
        print("✅ Database initialized successfully")
        
        # Try to query users
        try:
            session = get_session()
            users = session.query(User).all()
            print(f"✅ Successfully queried database. Found {len(users)} users.")
            return True
        except Exception as e:
            print(f"❌ Error querying database: {e}")
            return False
        finally:
            safe_close_session(session)
            
    except Exception as e:
        print(f"❌ Error testing database: {e}")
        return False

if __name__ == "__main__":
    print("🗄️ Testing Database Connection...")
    success = test_database()
    if not success:
        print("❌ Database test failed!")
        sys.exit(1)
    else:
        print("✅ Database test successful!")

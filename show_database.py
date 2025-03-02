
import os
import psycopg2
from psycopg2.extras import DictCursor

def get_db():
    return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=5)

def show_tables():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # List all tables
                cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                tables = [table[0] for table in cur.fetchall()]
                print("\n📊 DATABASE TABLES")
                print("==================")
                for table in tables:
                    print(f"- {table}")
                
                # Show table contents
                for table in tables:
                    print(f"\n📋 TABLE: {table.upper()}")
                    print("=" * (len(table) + 8))
                    
                    # Get column names
                    cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'")
                    columns = [col[0] for col in cur.fetchall()]
                    
                    # Get data
                    cur.execute(f"SELECT * FROM {table} LIMIT 10")
                    rows = cur.fetchall()
                    
                    if not rows:
                        print("No data in this table.")
                        continue
                    
                    # Calculate column widths for pretty printing
                    widths = {}
                    for i, col in enumerate(columns):
                        widths[i] = max(len(col), max([len(str(row[i])) for row in rows]))
                    
                    # Print header
                    header = " | ".join([col.ljust(widths[i]) for i, col in enumerate(columns)])
                    print(header)
                    print("-" * len(header))
                    
                    # Print rows
                    for row in rows:
                        print(" | ".join([str(val).ljust(widths[i]) for i, val in enumerate(row)]))
                    
                    # Print row count
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                    print(f"\nTotal rows: {count}")
                
    except Exception as e:
        print(f"Error connecting to database: {str(e)}")

if __name__ == "__main__":
    show_tables()

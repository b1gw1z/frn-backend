import os
import psycopg2

def enable_postgis():
    """
    Connects to the database directly and enables the PostGIS extension.
    This must run BEFORE 'flask db upgrade'.
    """
    db_url = os.getenv('DATABASE_URL')
    
    if not db_url:
        print("❌ DATABASE_URL not found.")
        return

    try:
        print("🌍 Connecting to Database to enable PostGIS...")
        # Connect to the DB
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        
        # Run the Magic Command
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        
        print("✅ PostGIS Extension Enabled Successfully!")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Failed to enable PostGIS: {e}")

if __name__ == "__main__":
    enable_postgis()
import os
import psycopg2
from urllib.parse import urlparse

def add_indexes():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not found.")
        return

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        
        print("🚀 Adding Speed Indexes...")
        
        # 1. Index for Login (Finds users instantly)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
        
        # 2. Index for Feed (Finds available food instantly)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_donations_status ON donations(status);")
        
        # 3. Index for History (Finds user items instantly)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_donations_donor ON donations(donor_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_claims_rescuer ON claims(rescuer_id);")
        
        print("✅ Database Optimized! Queries should be faster now.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    add_indexes()
    
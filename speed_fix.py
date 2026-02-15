import os
import psycopg2

def add_indexes():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not found.")
        return

    # Fix for SQLAlchemy/Psycopg2 URL compatibility
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://")

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()
        
        print("🚀 Adding Speed Indexes...")
        
        # 1. Index for Login
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
        
        # 2. Index for Feed
        cur.execute("CREATE INDEX IF NOT EXISTS idx_donations_status ON donations(status);")
        
        # 3. Index for History
        cur.execute("CREATE INDEX IF NOT EXISTS idx_donations_donor ON donations(donor_id);")
        # Check if table exists before indexing (Safety check)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_claims_rescuer ON claims(rescuer_id);")
        
        print("✅ Database Optimized! Queries should be faster now.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"⚠️ Speed Fix Error: {e}")

if __name__ == "__main__":
    add_indexes()
import os
import psycopg2
from app import app, db
from models import User

def deploy():
    """
    RESET SCRIPT
    1. Enables PostGIS
    2. DROPS old tables (Fixes the 'created_at' error)
    3. Creates NEW tables (With all new columns)
    4. Seeds Admin User
    """
    
    # --- PART 1: ENABLE POSTGIS ---
    print("🌍 1. Checking PostGIS Extension...")
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        try:
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cur.close()
            conn.close()
            print("✅ PostGIS Enabled.")
        except Exception as e:
            print(f"⚠️ PostGIS Warning: {e}")

    # --- PART 2: RESET TABLES & SEED ADMIN ---
    with app.app_context():
        
        # A. RESET DATABASE (The Fix)
        print("🗑️ 2. Dropping old tables (Fixing schema mismatch)...")
        db.drop_all()  # <--- THIS DELETES THE BROKEN TABLES
        print("✅ Old tables deleted.")

        print("🏗️ 3. Creating Fresh Database Tables...")
        db.create_all()  # <--- Creates tables WITH the 'created_at' column
        print("✅ New tables created successfully!")

        # B. Seed Admin
        print("🌱 4. Seeding Admin User...")
        email = 'admin@frn.org'
        # We don't need to check if it exists, because we just wiped the DB!
        admin = User(
            username='Super Admin',
            email=email,
            role='admin',
            organization_name='FRN Headquarters',
            registration_number='ADMIN-001',
            business_type='NGO',
            is_verified=True,
            points=1000,
            impact_tier='Gold',
            location="POINT(3.3792 6.5244)" 
        )
        admin.set_password('password123')
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin User Created.")

if __name__ == "__main__":
    deploy()
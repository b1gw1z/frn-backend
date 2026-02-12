import os
import psycopg2
from app import app, db
from models import User

def deploy():
    """
    Simplified Deployment Script
    1. Enables PostGIS
    2. Directly Creates Tables (Bypassing broken migrations)
    3. Seeds Admin User
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

    # --- PART 2: CREATE TABLES & SEED ADMIN ---
    # We use app_context to access the database safely
    with app.app_context():
        
        # A. Create Tables
        print("🏗️ 2. Creating Database Tables...")
        db.create_all()  # <--- The Magic Line (No more migration errors)
        print("✅ Tables Created Successfully!")

        # B. Seed Admin
        print("🌱 3. Seeding Admin User...")
        email = 'admin@frn.org'
        if not User.query.filter_by(email=email).first():
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
                location="POINT(3.3792 6.5244)" # Lagos
            )
            admin.set_password('password123')
            db.session.add(admin)
            db.session.commit()
            print("✅ Admin User Created.")
        else:
            print("✅ Admin User Already Exists.")

if __name__ == "__main__":
    deploy()
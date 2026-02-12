import os
import psycopg2
from app import app, db
from flask_migrate import upgrade
from models import User

def deploy():
    """
    Master Deployment Script
    1. Enables PostGIS
    2. Upgrades Database (Fixes the RuntimeError by using app_context)
    3. Seeds Admin User
    """
    
    # --- PART 1: ENABLE POSTGIS (Raw Connection) ---
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
            print(f"⚠️ PostGIS Warning (might already be on): {e}")

    # --- PART 2 & 3: FLASK CONTEXT OPERATIONS ---
    # We use 'with app.app_context():' to FIX the RuntimeError
    with app.app_context():
        
        # Run Migrations
        print("🔄 2. Running Database Migrations...")
        upgrade() # This is the manual version of 'flask db upgrade'
        print("✅ Migrations Success!")

        # Seed Admin
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
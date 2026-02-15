import os
import psycopg2
from app import create_app
from extensions import db
from models import User
from flask_migrate import upgrade

app = create_app()

def deploy():
    """
    PRODUCTION DEPLOY SCRIPT
    1. Enables PostGIS (Safe check)
    2. Upgrades DB Schema (Safe migration)
    3. Seeds Admin (Only if missing)
    """
    
    # --- PART 1: ENABLE POSTGIS (Safe) ---
    print("🌍 1. Checking PostGIS Extension...")
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        try:
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://")
                
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            cur.close()
            conn.close()
            print("✅ PostGIS check complete.")
        except Exception as e:
            print(f"⚠️ PostGIS Warning: {e}")

    with app.app_context():
        # --- PART 2: RUN MIGRATIONS (Instead of drop_all) ---
        print("🔄 2. Applying Database Migrations...")
        # This is the Python equivalent of running 'flask db upgrade'
        upgrade() 
        print("✅ Database schema is up to date.")

        # --- PART 3: SEED ADMIN (Conditional) ---
        print("🌱 3. Checking Admin User...")
        email = 'admin@frn.org'
        
        # KEY CHANGE: Check if admin exists before creating!
        existing_admin = User.query.filter_by(email=email).first()
        
        if not existing_admin:
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
            print("✅ Admin User Created (First Run).")
        else:
            print("ℹ️  Admin User already exists. Skipping.")

if __name__ == "__main__":
    deploy()
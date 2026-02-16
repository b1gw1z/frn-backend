import os
import psycopg2
from app import create_app
from extensions import db
from models import User
from flask_migrate import upgrade
from sqlalchemy import text  # <--- Needed to kill the ghost table

app = create_app()

def deploy():
    """
    SUPER-NUCLEAR DEPLOY SCRIPT (One-Time Fix)
    1. Wipes User Tables.
    2. Wipes the hidden 'alembic_version' table (The Ghost).
    3. Rebuilds using 'upgrade()' so migrations are perfectly synced.
    """
    with app.app_context():
        print("☢️  STARTING SUPER-NUCLEAR RESET...")

        # 1. Drop User Tables
        print("🗑️  Dropping all app tables...")
        db.drop_all()

        # 2. Drop the Hidden Ghost Table (The Real Fix)
        print("👻 Killing the ghost (alembic_version)...")
        try:
            with db.engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
                conn.commit() # Important for Postgres
            print("✅ Ghost deleted.")
        except Exception as e:
            print(f"⚠️ Warning dropping ghost: {e}")

        # 3. Rebuild using MIGRATIONS (This aligns DB and Code forever)
        print("🔄 Rebuilding database from Migrations...")
        upgrade()
        print("✅ Database matches code perfectly.")

        # 4. Seed Admin
        print("🌱 Seeding Admin...")
        email = 'admin@frn.org'
        admin = User(
            username='Super Admin',
            email=email,
            role='admin',
            organization_name='FRN Headquarters', 
            registration_number='ADMIN-001',
            business_type='NGO',
            is_verified=True,
            location="POINT(3.3792 6.5244)",
            phone="0800-FRN-HELP" # Phone number included
        )
        admin.set_password('password123')
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin User Created.")

if __name__ == "__main__":
    deploy()
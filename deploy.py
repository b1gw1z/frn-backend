# deploy.py (SAFE MODE)
import os
import psycopg2
from app import create_app
from extensions import db
from models import User
from flask_migrate import upgrade

app = create_app()

def deploy():
    # 1. Enable PostGIS (Safe Check)
    # ... (Keep your existing PostGIS check code here) ...

    with app.app_context():
        # 2. Run Migrations (Safe Update)
        print("🔄 Checking for database updates...")
        upgrade()
        print("✅ Database is up to date.")

        # 3. Check for Admin (Don't overwrite)
        if not User.query.filter_by(email='admin@frn.org').first():
            # ... (Seed code here) ...
            print("✅ Admin created.")
        else:
            print("ℹ️  Admin exists. Skipping.")

if __name__ == "__main__":
    deploy()
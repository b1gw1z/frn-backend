import os
import psycopg2
from app import create_app
from extensions import db
from models import User

app = create_app()

def deploy():
    """
    RESET SCRIPT (ONE TIME USE)
    1. Wipes the Cloud Database clean.
    2. Creates new tables (including Phone Number).
    3. Seeds Admin.
    """
    with app.app_context():
        # 1. The Nuclear Option: Fixes the 'Can't locate revision' error
        print("🗑️ NUKING DATABASE to fix migration mismatch...")
        db.drop_all()
        print("✅ Database wiped.")

        # 2. Rebuild
        print("mb️ Creating Fresh Tables...")
        db.create_all()
        print("✅ New tables created (with Phone Number column).")

        # 3. Seed Admin
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
            location="POINT(3.3792 6.5244)"
        )
        admin.set_password('password123')
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin User Created.")

if __name__ == "__main__":
    deploy()
from app import app, db
from models import User

def seed_admin():
    with app.app_context():
        # 1. Check if Admin exists
        if User.query.filter_by(email='admin@frn.org').first():
            print("✅ Admin user already exists. Skipping.")
            return

        # 2. Create Admin if not found
        print("🚀 Creating Admin User...")
        admin = User(
            username='Super Admin',
            email='admin@frn.org',
            role='admin',
            organization_name='FRN Headquarters',
            registration_number='ADMIN-001',
            business_type='NGO',
            is_verified=True,
            points=1000,
            impact_tier='Gold',
            location="POINT(3.3792 6.5244)" # Lagos coordinates
        )
        admin.set_password('password123')
        
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin Created Successfully!")

if __name__ == "__main__":
    seed_admin()
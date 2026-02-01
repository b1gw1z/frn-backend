from app import app, db
from sqlalchemy import text

with app.app_context():
    print("--- STARTING CLEANUP ---")
    
    # 1. Drop the specific tables defined in your models
    # This handles foreign keys and relationships automatically
    print("Dropping Users, Donations, and Claims...")
    db.drop_all()
    
    # 2. Manually drop the migration history table (which confuses Flask-Migrate)
    print("Dropping migration history...")
    try:
        db.session.execute(text("DROP TABLE IF EXISTS alembic_version;"))
        db.session.commit()
    except Exception as e:
        print(f"Minor note: {e}")

    print("--- SUCCESS: Database is now 100% empty tables ---")
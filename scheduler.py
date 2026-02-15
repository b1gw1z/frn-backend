from extensions import db, scheduler, mail
from models import Donation, User
from flask_mail import Message
from datetime import datetime

def init_scheduler(app):
    """ Starts the background clock """
    # Note: We do NOT create a new APScheduler() here. 
    # We use the one imported from extensions.py to avoid circular errors.
    scheduler.init_app(app)
    scheduler.start()
    print("⏰ Scheduler Started: Watching for expired food & tasks...")

# ==========================================
#  TASK 1: AUTO-EXPIRE FOOD
# ==========================================
# Runs every hour (at minute 0)
@scheduler.task('cron', id='expire_food', minute=0)
def expire_food_job():
    """
    Checks for items past their expiration date.
    Marks them as 'expired' so they stop showing up in search.
    """
    # We must use scheduler.app.app_context() because this runs in the background
    with scheduler.app.app_context():
        now = datetime.now()
        
        # Find items that are 'available' BUT technically expired
        expired_items = Donation.query.filter(
            Donation.status == 'available', 
            Donation.expiration_date < now
        ).all()

        if not expired_items:
            # print(f"✅ No expired items found at {now}")
            return

        count = 0
        for d in expired_items:
            d.status = 'expired'
            count += 1

        try:
            db.session.commit()
            print(f"⚠️  Scheduler: Marked {count} items as EXPIRED.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Scheduler Error: {e}")

# ==========================================
#  TASK 2: DAILY DONOR REMINDER (Alerts)
# ==========================================
# Runs every day at 9:00 AM
@scheduler.task('cron', id='daily_reminder', hour=9)
def daily_reminder_job():
    """
    Sends a friendly reminder to Donors to check their inventory.
    (Replaces the Real-Time Watchlist check, which is now handled in donations.py)
    """
    with scheduler.app.app_context():
        # Find verified donors
        donors = User.query.filter_by(role='donor', is_verified=True).all()
        
        if not donors:
            return

        print(f"📧 Scheduler: Sending daily reminders to {len(donors)} donors...")
        
        with mail.connect() as conn:
            for donor in donors:
                try:
                    msg = Message(
                        subject="Good Morning! Have food to rescue today?",
                        recipients=[donor.email],
                        body=f"Hello {donor.organization_name},\n\nThis is your daily reminder from FRN. If you have any surplus food, please post it now to help those in need.\n\nLogin here: https://frn-nigeria.vercel.app/login"
                    )
                    conn.send(msg)
                except Exception as e:
                    print(f"Failed to email {donor.email}: {e}")
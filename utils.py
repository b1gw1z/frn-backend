from models import AuditLog, Donation, db
from flask import url_for
from flask_mail import Message
from extensions import mail
from datetime import datetime

def log_activity(user_id, action, details):
    try:
        new_log = AuditLog(user_id=user_id, action=action, details=details)
        db.session.add(new_log)
        db.session.commit()
    except Exception as e:
        print(f"⚠️ Logging Failed: {e}") # Don't crash the app if logging fails
        


def send_verification_email(user):
    token = user.get_verification_token()
    
    # In a real app, this link points to your Frontend Verify Page
    # Example: https://your-frontend.vercel.app/verify?token=...
    # For now, we can point it to the backend for testing:
    link = url_for('verify_email', token=token, _external=True)
    
    msg = Message('Verify Your Account - Food Rescue Network',
                  recipients=[user.email])
    
    msg.body = f'''Hello {user.organization_name},

Welcome to the Food Rescue Network!

To activate your account, please verify your email by clicking the link below:

{link}

If you did not register, please ignore this email.
'''
    try:
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")        
        
def update_expired_status():
    """
    Checks for items that have passed their expiration date
    and updates their status to 'expired' in the database.
    Also logs this event for Admins.
    """
    now = datetime.now()
    # Find items that are 'available' BUT have passed their time
    expired_items = Donation.query.filter(
        Donation.status == 'available', 
        Donation.expiration_date < now
    ).all()

    if not expired_items:
        return

    for d in expired_items:
        d.status = 'expired'
        # 📝 Log for Admin
        log_activity(d.donor_id, "EXPIRED", f"Donation '{d.title}' expired automatically.")
        print(f"⚠️ Marked {d.title} as expired.")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error updating expired items: {e}")        
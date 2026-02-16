from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import deferred
from extensions import db
import secrets
import jwt
from flask import current_app

# ==========================================
#  1. USER MODEL
# ==========================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    
    # --- B2B FIELDS ---
    role = db.Column(db.String(20), nullable=False)
    organization_name = db.Column(db.String(150), nullable=False) 
    registration_number = db.Column(db.String(50), unique=True, nullable=False)
    business_type = db.Column(db.String(50), nullable=False)
    
    # --- GAMIFICATION ---
    points = db.Column(db.Integer, default=0)
    impact_tier = db.Column(db.String(50), default="Newcomer")
    
    # --- SECURITY ---
    is_verified = db.Column(db.Boolean, default=False)
    verification_proof = db.Column(db.String(255), nullable=True)
    
    # --- TIMESTAMPS ---
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)) # <--- ADDED
    
    # --- GEOLOCATION (LAZY LOADED) ---
    location = db.Column(Geometry(geometry_type='POINT', srid=4326))
    
    donations = db.relationship('Donation', backref='donor', lazy=True)
    claims = db.relationship('Claim', backref='rescuer', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_verification_token(self, expires_sec=86400):
        """Generates a JWT token for email verification."""
        s = jwt.encode(
            {
                "user_id": self.id,
                "exp": datetime.now(timezone.utc) + timedelta(seconds=expires_sec)
            },
            current_app.config['SECRET_KEY'],
            algorithm="HS256"
        )
        return s

    @staticmethod
    def verify_token(token):
        """Decodes the token and returns the User."""
        try:
            user_id = jwt.decode(
                token,
                current_app.config['SECRET_KEY'],
                algorithms=["HS256"]
            )['user_id']
        except:
            return None
        return db.session.get(User, user_id)

# ==========================================
#  2. DONATION MODEL
# ==========================================
class Donation(db.Model):
    __tablename__ = 'donations'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    initial_quantity_kg = db.Column(db.Float)
    quantity_kg = db.Column(db.Float)
    
    food_type = db.Column(db.String(50)) 
    tags = db.Column(db.String(200))
    image_url = db.Column(db.String(500))
    
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='available')
    
    # --- TIMESTAMPS ---
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    expiration_date = db.Column(db.DateTime, nullable=True)
    
    claims = db.relationship('Claim', backref='donation', lazy=True)

# ==========================================
#  3. CLAIM MODEL
# ==========================================
class Claim(db.Model):
    __tablename__ = 'claims'
    
    id = db.Column(db.Integer, primary_key=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), nullable=False)
    rescuer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    quantity_claimed = db.Column(db.Float, nullable=False)
    
    # --- TIME TRACKING ---
    claimed_at = db.Column(db.DateTime, server_default=db.func.now()) # Acts as Created At
    picked_up_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)) # <--- ADDED
    
    # --- VERIFICATION & SECURITY ---
    pickup_code = db.Column(db.String(10), unique=True, nullable=True)
    
    status = db.Column(db.String(20), default='pending_pickup') 

    def generate_code(self):
        self.pickup_code = secrets.token_hex(3).upper()

# ==========================================
#  4. MESSAGE MODEL
# ==========================================
class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now()) # Acts as Created At
    
    
class Contact(db.Model):
    """
    Allows a user to save a specific nickname for another user.
    Example: Rescuer saves 'John Doe' as 'The Rice Guy'.
    This is PRIVATE to the 'owner'.
    """
    __tablename__ = 'contacts'
    
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # Me
    contact_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # The person I'm chatting with
    nickname = db.Column(db.String(100), nullable=True)
    
    # Ensure I can't have two entries for the same person
    __table_args__ = (db.UniqueConstraint('owner_id', 'contact_user_id', name='_user_contact_uc'),)    

# ==========================================
#  5. AUDIT LOG MODEL
# ==========================================
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    details = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, server_default=db.func.now()) # Acts as Created At
    
    user = db.relationship('User', backref='logs')    

# ==========================================
#  6. REPORT MODEL
# ==========================================
class Report(db.Model):
    __tablename__ = 'reports'
    
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now()) # Acts as Created At
    status = db.Column(db.String(20), default='pending')

    reporter = db.relationship('User', backref='reports_filed')
    donation = db.relationship('Donation', backref='reports')
    
class Ticket(db.Model):
    __tablename__ = 'tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Optional: Link to a specific transaction if relevant
    claim_id = db.Column(db.Integer, db.ForeignKey('claims.id'), nullable=True) 
    
    subject = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='open') # open, in_progress, resolved
    priority = db.Column(db.String(20), default='medium') # low, medium, high
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # Resolution details (what did the admin say?)
    admin_response = db.Column(db.Text, nullable=True)

    # Relationship
    reporter = db.relationship('User', backref='tickets')
    claim = db.relationship('Claim', backref='tickets')  
    

class Watchlist(db.Model):
    __tablename__ = 'watchlists'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    food_type = db.Column(db.String(50), nullable=False) # e.g., "Grain", "Cooked Meal"
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', backref='watchlist_items')      
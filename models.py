from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# ==========================================
#  1. USER MODEL (Unchanged)
# ==========================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
    role = db.Column(db.String(20), nullable=False)
    organization_name = db.Column(db.String(150), nullable=False) 
    registration_number = db.Column(db.String(50), unique=True, nullable=False)
    business_type = db.Column(db.String(50), nullable=False)
    
    points = db.Column(db.Integer, default=0)
    impact_tier = db.Column(db.String(50), default="Newcomer")
    
    is_verified = db.Column(db.Boolean, default=False)
    verification_proof = db.Column(db.String(255), nullable=True)
    
    location = db.Column(Geometry(geometry_type='POINT', srid=4326))

    donations = db.relationship('Donation', backref='donor', lazy=True)
    claims = db.relationship('Claim', backref='rescuer', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ==========================================
#  2. DONATION MODEL (Updated for History)
# ==========================================
class Donation(db.Model):
    __tablename__ = 'donations'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    # TRACKING STOCK
    initial_quantity_kg = db.Column(db.Float) # <--- NEW: What they started with
    quantity_kg = db.Column(db.Float)         # <--- EXISTING: What is left right now
    
    food_type = db.Column(db.String(50)) 
    tags = db.Column(db.String(200))
    image_url = db.Column(db.String(500))
    
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='available') # 'available', 'partially_claimed', 'claimed'
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    expiration_date = db.Column(db.DateTime, nullable=True)
    
    # Relationship to track all partial claims on this item
    claims = db.relationship('Claim', backref='donation', lazy=True)

# ==========================================
#  3. CLAIM MODEL (Updated for Ledger)
# ==========================================
class Claim(db.Model):
    __tablename__ = 'claims'
    id = db.Column(db.Integer, primary_key=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), nullable=False) # Removed unique=True to allow multiple claims
    rescuer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    quantity_claimed = db.Column(db.Float, nullable=False) # <--- NEW: How much THEY took
    
    claimed_at = db.Column(db.DateTime, server_default=db.func.now())
    picked_up_at = db.Column(db.DateTime, nullable=True)

# ==========================================
#  4. MESSAGE MODEL (Unchanged)
# ==========================================
class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
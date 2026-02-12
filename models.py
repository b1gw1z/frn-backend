from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy.orm import deferred  # <--- NEW IMPORT

db = SQLAlchemy()

# ==========================================
#  1. USER MODEL
# ==========================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
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
    
    # --- GEOLOCATION (LAZY LOADED) ---
    # We wrap this in 'deferred()' so it is NOT loaded during login.
    # It will only load when we explicitly use it (like in the map search).
    location = deferred(db.Column(Geometry(geometry_type='POINT', srid=4326)))

    donations = db.relationship('Donation', backref='donor', lazy=True)
    claims = db.relationship('Claim', backref='rescuer', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

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
    created_at = db.Column(db.DateTime, server_default=db.func.now())
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
    
    claimed_at = db.Column(db.DateTime, server_default=db.func.now())
    picked_up_at = db.Column(db.DateTime, nullable=True)

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
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
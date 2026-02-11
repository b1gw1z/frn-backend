from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# ==========================================
#  1. USER MODEL (Gamified & Verified)
# ==========================================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # --- B2B & NGO FIELDS ---
    role = db.Column(db.String(20), nullable=False) # 'donor', 'rescuer', 'admin'
    organization_name = db.Column(db.String(150), nullable=False) 
    registration_number = db.Column(db.String(50), unique=True, nullable=False)
    business_type = db.Column(db.String(50), nullable=False) # e.g. 'Restaurant', 'NGO'
    
    # --- GAMIFICATION & STATS ---
    points = db.Column(db.Integer, default=0) # Tracks total impact
    impact_tier = db.Column(db.String(50), default="Newcomer") # Bronze, Silver, Gold, Sapphire
    
    # --- SECURITY ---
    is_verified = db.Column(db.Boolean, default=False)
    verification_proof = db.Column(db.String(255), nullable=True) # Link to documents
    
    # --- GEOLOCATION ---
    # srid=4326 is standard GPS (Lat/Lon)
    location = db.Column(Geometry(geometry_type='POINT', srid=4326))

    # --- RELATIONSHIPS ---
    donations = db.relationship('Donation', backref='donor', lazy=True)
    claims = db.relationship('Claim', backref='rescuer', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# ==========================================
#  2. DONATION MODEL (Images & Tags)
# ==========================================
class Donation(db.Model):
    __tablename__ = 'donations'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    quantity_kg = db.Column(db.Float)
    
    # --- NEW FLEXIBLE FIELDS ---
    food_type = db.Column(db.String(50)) # Cooked, Raw, Packaged
    tags = db.Column(db.String(200)) # e.g., "#Compost, #AnimalFeed" (Flexible Tagging)
    image_url = db.Column(db.String(500)) # Link to photo of food
    
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='available') # available, claimed
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    expiration_date = db.Column(db.DateTime, nullable=True)
    
    claim = db.relationship('Claim', backref='donation', uselist=False)

# ==========================================
#  3. CLAIM MODEL (History Tracking)
# ==========================================
class Claim(db.Model):
    __tablename__ = 'claims'

    id = db.Column(db.Integer, primary_key=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), unique=True, nullable=False)
    rescuer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    claimed_at = db.Column(db.DateTime, server_default=db.func.now())
    picked_up_at = db.Column(db.DateTime, nullable=True)

# ==========================================
#  4. MESSAGE MODEL (Chat)
# ==========================================
class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), nullable=False)
    
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
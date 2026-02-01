from flask_sqlalchemy import SQLAlchemy
from geoalchemy2 import Geometry
from flask_login import UserMixin 

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False) # 'donor' or 'rescuer'
    password_hash = db.Column(db.String(256), nullable=False)

    # Note: srid=4326 is standard GPS. No 'geography=True' to avoid errors.
    location = db.Column(Geometry(geometry_type='POINT', srid=4326))

    donations = db.relationship('Donation', backref='donor', lazy=True)
    claims = db.relationship('Claim', backref='rescuer', lazy=True)
    is_verified = db.Column(db.Boolean, default=False)

class Donation(db.Model):
    __tablename__ = 'donations'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    quantity_kg = db.Column(db.Float)
    food_type = db.Column(db.String(50))
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), default='available')
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    
    claim = db.relationship('Claim', backref='donation', uselist=False)
    expiration_date = db.Column(db.DateTime, nullable=True)

class Claim(db.Model):
    __tablename__ = 'claims'

    id = db.Column(db.Integer, primary_key=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), unique=True, nullable=False)
    rescuer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    claimed_at = db.Column(db.DateTime, server_default=db.func.now())
    picked_up_at = db.Column(db.DateTime, nullable=True)
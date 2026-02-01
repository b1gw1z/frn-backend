from flask import request, jsonify
from app import app, db
from models import User
from werkzeug.security import generate_password_hash, check_password_hash 
from models import Donation
from models import Claim
from models import Message
from sqlalchemy import func
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()

    required = ['username', 'email', 'password', 'role', 'latitude', 'longitude']
    if not all(field in data for field in required):
        return jsonify({'error': 'Missing required fields'}), 400

    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already registered'}), 400

    hashed_password = generate_password_hash(data['password'])

    # Format location for PostGIS: POINT(longitude latitude)
    new_user = User(
        username=data['username'],
        email=data['email'],
        password_hash=hashed_password,
        role=data['role'],
        location=f"POINT({data['longitude']} {data['latitude']})" 
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'message': 'User registered successfully!'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing email or password'}), 400

    user = User.query.filter_by(email=data['email']).first()

    if user and check_password_hash(user.password_hash, data['password']):
        # Generate the digital "Badge" (Token)
        # We hide the user's ID inside the token so we can read it later
        access_token = create_access_token(identity=str(user.id))
        
        return jsonify({
            'message': 'Login successful!',
            'access_token': access_token,  # <--- Send token to user
            'user': {'username': user.username, 'role': user.role}
        }), 200
    else:
        return jsonify({'error': 'Invalid email or password'}), 401    

# --- CREATE DONATION ENDPOINT ---
@app.route('/api/donations', methods=['POST'])
@jwt_required()
def create_donation():
    data = request.get_json()
    current_user_id = get_jwt_identity()

    # Check required fields
    required_fields = ['title', 'description', 'quantity_kg', 'food_type']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    # Parse the expiration date if provided
    exp_date = None
    if 'expiration_date' in data:
        try:
            # Expecting format like "2026-12-31" or "2026-12-31 15:00:00"
            exp_date = datetime.fromisoformat(data['expiration_date'])
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

    new_donation = Donation(
        title=data['title'],
        description=data['description'],
        quantity_kg=data['quantity_kg'],
        food_type=data['food_type'],
        donor_id=current_user_id,
        status='available',
        expiration_date=exp_date # <--- Save the date!
    )

    try:
        db.session.add(new_donation)
        db.session.commit()
        return jsonify({'message': 'Donation created successfully!', 'donation_id': new_donation.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
   # --- GET DONATIONS (With Distance Calculation) ---
@app.route('/api/donations', methods=['GET'])
def get_donations():
    # 1. Get Rescuer's location
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    results = []

    if lat and lng:
        # Create a point from the rescuer's coordinates
        rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        
        # 2. THE FIX: Join with the User table!
        # We calculate distance using User.location, not Donation.location
        donations_with_dist = db.session.query(
            Donation, 
            func.ST_DistanceSphere(User.location, rescuer_location).label('distance')
        ).join(User).filter(Donation.status == 'available').all()

        for donation, distance_meters in donations_with_dist:
            results.append({
                'id': donation.id,
                'title': donation.title,
                'description': donation.description,
                'quantity_kg': donation.quantity_kg,
                'food_type': donation.food_type,
                'donor_id': donation.donor_id,
                'distance_km': round(distance_meters / 1000, 2) # Convert to KM
            })
            
    else:
        # Fallback if no location provided
        donations = Donation.query.filter_by(status='available').all()
        for donation in donations:
            results.append({
                'id': donation.id,
                'title': donation.title,
                'description': donation.description,
                'quantity_kg': donation.quantity_kg,
                'food_type': donation.food_type,
                'donor_id': donation.donor_id,
                'distance_km': None
            })

    return jsonify({'donations': results}), 200


# --- CLAIM DONATION ENDPOINT ---
@app.route('/api/claim', methods=['POST'])
@jwt_required()  # <--- 1. Lock the door
def claim_donation():
    data = request.get_json()
    current_user_id = get_jwt_identity() # <--- 2. Get Rescuer ID from Token

    # Validation
    if not data.get('donation_id'):
        return jsonify({'error': 'Missing donation_id'}), 400

    donation = Donation.query.get(data['donation_id'])
    
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    if donation.status != 'available':
        return jsonify({'error': 'This donation has already been claimed'}), 400

    # Create the Claim using the ID from the token
    new_claim = Claim(
        donation_id=data['donation_id'],
        rescuer_id=current_user_id 
    )

    donation.status = 'claimed'

    try:
        db.session.add(new_claim)
        db.session.commit()
        return jsonify({'message': 'Donation claimed successfully!'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
    # In routes.py

@app.route('/api/admin/verify_user/<int:user_id>', methods=['PATCH'])
@jwt_required()
def verify_user(user_id):
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)
    
    # Check if the requester is actually an Admin
    if not admin or admin.role != 'admin':
        return jsonify({'error': 'Access denied. Admins only.'}), 403

    user_to_verify = User.query.get(user_id)
    if not user_to_verify:
        return jsonify({'error': 'User not found'}), 404

    user_to_verify.is_verified = True
    db.session.commit()
    
    return jsonify({'message': f'User {user_to_verify.username} has been verified!'}), 200

# --- ADMIN: VERIFY USER ---
@app.route('/api/admin/verify/<int:user_id>', methods=['PATCH'])
@jwt_required()
def verify_user_alt(user_id):
    # 1. Check if the requester is an Admin
    current_user_id = get_jwt_identity()
    admin_user = User.query.get(current_user_id)
    
    if not admin_user or admin_user.role != 'admin':
        return jsonify({'error': 'Access denied. Admins only.'}), 403

    # 2. Find the user to verify
    user_to_verify = User.query.get(user_id)
    if not user_to_verify:
        return jsonify({'error': 'User not found'}), 404

    # 3. Update status
    user_to_verify.is_verified = True
    db.session.commit()

    return jsonify({'message': f'User {user_to_verify.username} is now verified!'}), 200

# --- CHAT: SEND MESSAGE ---
@app.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    data = request.get_json()
    sender_id = get_jwt_identity()

    if not data.get('receiver_id') or not data.get('donation_id') or not data.get('text'):
        return jsonify({'error': 'Missing fields'}), 400

    new_msg = Message(
        sender_id=sender_id,
        receiver_id=data['receiver_id'],
        donation_id=data['donation_id'],
        text=data['text']
    )
    db.session.add(new_msg)
    db.session.commit()
    return jsonify({'message': 'Message sent!'}), 201

# --- CHAT: GET MESSAGES ---
@app.route('/api/messages/<int:donation_id>', methods=['GET'])
@jwt_required()
def get_messages(donation_id):
    # Get all messages for a specific donation ID
    msgs = Message.query.filter_by(donation_id=donation_id).order_by(Message.timestamp).all()
    
    output = []
    for m in msgs:
        output.append({
            'sender_id': m.sender_id,
            'text': m.text,
            'timestamp': m.timestamp
        })
    return jsonify({'messages': output}), 200

# --- ADMIN: ANALYTICS DASHBOARD ---
@app.route('/api/admin/stats', methods=['GET'])
@jwt_required()
def get_stats():
    # Security Check
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if not user or user.role != 'admin':
        return jsonify({'error': 'Admins only'}), 403

    # Calculate Stats
    total_donations = Donation.query.count()
    active_claims = Claim.query.count()
    users_count = User.query.count()
    
    return jsonify({
        'total_donations': total_donations,
        'successful_claims': active_claims,
        'total_users': users_count
    }), 200
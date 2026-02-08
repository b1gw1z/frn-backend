from flask import request, jsonify
from app import app, db
from models import User, Donation, Claim, Message
from werkzeug.security import generate_password_hash, check_password_hash 
from sqlalchemy import func
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime

# =======================================================
#  SECTION 1: AUTHENTICATION & REGISTRATION
# =======================================================

@app.route('/api/register', methods=['POST'])
def register():
    """
    Registers a new Business or NGO.
    Requires: Email, Password, Organization Name, CAC Number, Proof Link.
    Default Status: Unverified (Cannot use app until Admin approves).
    """
    data = request.get_json()

    # 1.1 Strict B2B Validation
    required_fields = ['email', 'password', 'role', 'latitude', 'longitude', 
                       'organization_name', 'registration_number', 'business_type', 
                       'verification_proof']
    
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # 1.2 Prevent Duplicates (Email or CAC Number)
    if User.query.filter((User.email == data['email']) | (User.registration_number == data['registration_number'])).first():
        return jsonify({'error': 'Email or CAC Registration Number already exists'}), 400

    # 1.3 Geospatial Point Creation
    point = f"POINT({data['longitude']} {data['latitude']})"
    
    # 1.4 Create User (Default: is_verified = False)
    new_user = User(
        username=data['organization_name'], 
        email=data['email'],
        role=data['role'].lower(), 
        organization_name=data['organization_name'],
        registration_number=data['registration_number'],
        business_type=data['business_type'],
        verification_proof=data['verification_proof'],
        location=point,
        is_verified=False 
    )
    
    new_user.set_password(data['password'])
    
    try:
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'message': 'Registration successful! Your account is pending verification.'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """
    Logs in a user and returns their B2B Profile & Verification Status.
    """
    data = request.get_json()

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing email or password'}), 400

    user = User.query.filter_by(email=data['email']).first()

    if user and check_password_hash(user.password_hash, data['password']):
        
        # 👇 UPDATE THIS SECTION 👇
        # We now add "claims" (extra info) inside the token so the frontend can read it.
        additional_claims = {"role": user.role}
        access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
        
        return jsonify({
            'message': 'Login successful!',
            'access_token': access_token,
            'user': {
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'organization_name': user.organization_name, 
                'business_type': user.business_type,         
                'registration_number': user.registration_number,
                'is_verified': user.is_verified,  # <--- CRITICAL: Frontend checks this
                'verification_proof': user.verification_proof 
            }
        }), 200
    else:
        return jsonify({'error': 'Invalid email or password'}), 401    


# =======================================================
#  SECTION 2: REAL-TIME MONITORING & DASHBOARDS
# =======================================================

@app.route('/api/admin/stats', methods=['GET'])
@jwt_required()
def get_admin_stats():
    """
    ADMIN DASHBOARD: Returns system-wide live metrics.
    Used by the Admin Panel to show "Total Food Rescued", "Pending Users", etc.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or user.role != 'admin':
        return jsonify({'error': 'Admins only'}), 403

    # Calculate total weight of food rescued
    total_kg = db.session.query(func.sum(Donation.quantity_kg)).scalar() or 0

    return jsonify({
        'total_donations': Donation.query.count(),
        'successful_claims': Claim.query.count(),
        'total_users': User.query.count(),
        'pending_verifications': User.query.filter_by(is_verified=False).count(),
        'total_food_rescued_kg': round(total_kg, 1)
    }), 200

@app.route('/api/donor/stats', methods=['GET'])
@jwt_required()
def get_donor_stats():
    """
    DONOR DASHBOARD: Returns CSR impact data for the specific business.
    """
    current_user_id = get_jwt_identity()
    
    # 1. Total Donations by this donor
    my_donations = Donation.query.filter_by(donor_id=current_user_id).count()
    
    # 2. Total Weight Donated
    total_weight = db.session.query(func.sum(Donation.quantity_kg))\
        .filter_by(donor_id=current_user_id).scalar() or 0
        
    # 3. Active Listings
    active_listings = Donation.query.filter_by(donor_id=current_user_id, status='available').count()

    return jsonify({
        'total_donations_count': my_donations,
        'total_kg_donated': round(total_weight, 1),
        'active_listings': active_listings,
        'impact_message': f"You have saved {round(total_weight, 1)}kg of food from going to waste!"
    }), 200

@app.route('/api/recipient/stats', methods=['GET'])
@jwt_required()
def get_recipient_stats():
    """
    RECIPIENT DASHBOARD: Returns impact data for the NGO.
    """
    current_user_id = get_jwt_identity()
    
    my_claims_count = Claim.query.filter_by(rescuer_id=current_user_id).count()
    
    total_rescued = db.session.query(func.sum(Donation.quantity_kg))\
        .join(Claim, Claim.donation_id == Donation.id)\
        .filter(Claim.rescuer_id == current_user_id).scalar() or 0

    return jsonify({
        'total_claims': my_claims_count,
        'total_kg_rescued': round(total_rescued, 1),
        'impact_message': f"Your NGO has distributed {round(total_rescued, 1)}kg of food to the needy."
    }), 200


# =======================================================
#  SECTION 3: ADMIN VERIFICATION TOOLS
# =======================================================

@app.route('/api/admin/pending-users', methods=['GET'])
@jwt_required()
def get_pending_users():
    """
    Returns a list of all users where is_verified = False.
    Admin uses this to see who needs approval.
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)
    
    if not admin or admin.role != 'admin':
        return jsonify({'error': 'Access denied. Admins only.'}), 403

    pending = User.query.filter_by(is_verified=False).all()
    
    output = []
    for u in pending:
        output.append({
            'id': u.id,
            'organization_name': u.organization_name,
            'registration_number': u.registration_number,
            'email': u.email,
            'business_type': u.business_type,
            'verification_proof': u.verification_proof # Admin clicks this link to check doc
        })

    return jsonify(output), 200

@app.route('/api/admin/verify/<int:user_id>', methods=['PATCH'])
@jwt_required()
def verify_user(user_id):
    """
    Admin clicks "Approve" -> This endpoint sets is_verified = True.
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)
    
    if not admin or admin.role != 'admin':
        return jsonify({'error': 'Access denied. Admins only.'}), 403

    user_to_verify = User.query.get(user_id)
    if not user_to_verify:
        return jsonify({'error': 'User not found'}), 404

    user_to_verify.is_verified = True
    db.session.commit()

    return jsonify({'message': f'{user_to_verify.organization_name} has been verified!'}), 200


# =======================================================
#  SECTION 4: DONATION MANAGEMENT (GEO-SEARCH)
# =======================================================

@app.route('/api/donations', methods=['POST'])
@jwt_required()
def create_donation():
    """
    Allows Verified Donors to post food.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # 4.1 SECURITY: Check Verification
    if not user.is_verified:
        return jsonify({'error': 'Account not verified. You cannot post donations yet.'}), 403

    if user.role != 'donor':
        return jsonify({'error': 'Only Donors (Businesses) can post food.'}), 403

    data = request.get_json()
    
    required_fields = ['title', 'description', 'quantity_kg', 'food_type']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    exp_date = None
    if 'expiration_date' in data:
        try:
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
        expiration_date=exp_date
    )

    try:
        db.session.add(new_donation)
        db.session.commit()
        return jsonify({'message': 'Donation posted successfully!', 'donation_id': new_donation.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/donations', methods=['GET'])
def get_donations():
    """
    Returns available donations.
    If lat/lng provided: Sorts by distance (Nearest First).
    If no lat/lng: Returns list by date.
    """
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    results = []

    if lat and lng:
        # 4.2 Geospatial Search (PostGIS)
        rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        
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
                'organization_name': donation.donor.organization_name,
                'expiration_date': donation.expiration_date,
                'distance_km': round(distance_meters / 1000, 2)
            })
    else:
        # 4.3 Standard List
        donations = Donation.query.filter_by(status='available').all()
        for donation in donations:
            results.append({
                'id': donation.id,
                'title': donation.title,
                'description': donation.description,
                'organization_name': donation.donor.organization_name,
                'quantity_kg': donation.quantity_kg,
                'distance_km': None
            })

    return jsonify({'donations': results}), 200


# =======================================================
#  SECTION 5: CLAIMS & MESSAGING
# =======================================================

@app.route('/api/claim', methods=['POST'])
@jwt_required()
def claim_donation():
    """
    Allows Verified Recipients to claim food.
    """
    data = request.get_json()
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    # 5.1 SECURITY: Check Verification
    if not user.is_verified:
        return jsonify({'error': 'Account not verified. You cannot claim food yet.'}), 403

    if not data.get('donation_id'):
        return jsonify({'error': 'Missing donation_id'}), 400

    donation = Donation.query.get(data['donation_id'])
    
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    if donation.status != 'available':
        return jsonify({'error': 'This donation has already been claimed'}), 400

    new_claim = Claim(
        donation_id=data['donation_id'],
        rescuer_id=current_user_id 
    )

    donation.status = 'claimed'

    try:
        db.session.add(new_claim)
        db.session.commit()
        return jsonify({'message': 'Donation claimed! Please contact the donor to arrange pickup.'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

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

@app.route('/api/messages/<int:donation_id>', methods=['GET'])
@jwt_required()
def get_messages(donation_id):
    msgs = Message.query.filter_by(donation_id=donation_id).order_by(Message.timestamp).all()
    output = []
    for m in msgs:
        output.append({
            'sender_id': m.sender_id,
            'text': m.text,
            'timestamp': m.timestamp
        })
    return jsonify({'messages': output}), 200
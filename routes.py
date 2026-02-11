import csv
import io
from flask import request, jsonify, make_response
from app import app, db
from models import User, Donation, Claim, Message
from werkzeug.security import generate_password_hash, check_password_hash 
from sqlalchemy import func, desc
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime

# =======================================================
#  SECTION 1: AUTHENTICATION & REGISTRATION
# =======================================================

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()

    # 1.1 Strict B2B Validation
    required_fields = ['email', 'password', 'role', 'latitude', 'longitude', 
                       'organization_name', 'registration_number', 'business_type']
    
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    if User.query.filter((User.email == data['email']) | (User.registration_number == data['registration_number'])).first():
        return jsonify({'error': 'Email or CAC Registration Number already exists'}), 400

    # Create Point for PostGIS
    point = f"POINT({data['longitude']} {data['latitude']})"
    
    new_user = User(
        username=data['organization_name'], 
        email=data['email'],
        role=data['role'].lower(), 
        organization_name=data['organization_name'],
        registration_number=data['registration_number'],
        business_type=data['business_type'],
        verification_proof=data.get('verification_proof'),
        location=point,
        is_verified=False,
        points=0,           
        impact_tier="Newcomer"
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
    data = request.get_json()

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing email or password'}), 400

    user = User.query.filter_by(email=data['email']).first()

    if user and check_password_hash(user.password_hash, data['password']):
        
        # Add Role & Org Name to Token
        additional_claims = {"role": user.role, "org": user.organization_name}
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
                'is_verified': user.is_verified, 
                'points': user.points,        
                'impact_tier': user.impact_tier
            }
        }), 200
    else:
        return jsonify({'error': 'Invalid email or password'}), 401    


# =======================================================
#  SECTION 2: GAMIFICATION & LEADERBOARDS
# =======================================================

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """ Returns Top 10 Donors based on points. """
    top_donors = User.query.filter_by(role='donor')\
        .order_by(desc(User.points))\
        .limit(10).all()
        
    results = []
    for user in top_donors:
        results.append({
            'organization_name': user.organization_name,
            'points': user.points,
            'tier': user.impact_tier,
            'business_type': user.business_type
        })
    return jsonify(results), 200


# =======================================================
#  SECTION 3: ADMIN DASHBOARD (System Stats)
# =======================================================

@app.route('/api/admin/stats', methods=['GET'])
@jwt_required()
def get_admin_stats():
    """ Returns system-wide live metrics. """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user or user.role != 'admin':
        return jsonify({'error': 'Admins only'}), 403

    total_kg = db.session.query(func.sum(Donation.quantity_kg)).scalar() or 0
    
    donor_count = User.query.filter_by(role='donor').count()
    recipient_count = User.query.filter_by(role='rescuer').count()

    return jsonify({
        'total_food_rescued_kg': round(total_kg, 1),
        'total_donations': Donation.query.count(),
        'successful_claims': Claim.query.count(),
        'total_users': User.query.count(),
        'user_breakdown': {
            'donors': donor_count,
            'recipients': recipient_count
        },
        'pending_verifications': User.query.filter_by(is_verified=False).count()
    }), 200

# =======================================================
#  SECTION 4: DONATION MANAGEMENT (Map Enabled!)
# =======================================================

@app.route('/api/donations', methods=['POST'])
@jwt_required()
def create_donation():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user.is_verified:
        return jsonify({'error': 'Account not verified. You cannot post donations yet.'}), 403

    if user.role != 'donor':
        return jsonify({'error': 'Only Donors (Businesses) can post food.'}), 403

    data = request.get_json()
    
    required_fields = ['title', 'description', 'quantity_kg', 'food_type']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    # --- GAMIFICATION LOGIC (1kg = 10 Points) ---
    try:
        kg_amount = float(data['quantity_kg'])
        points_earned = int(kg_amount * 10)
        user.points += points_earned
        
        # Update Tier
        if user.points >= 5000: user.impact_tier = "Sapphire"
        elif user.points >= 2000: user.impact_tier = "Gold"
        elif user.points >= 500: user.impact_tier = "Silver"
        else: user.impact_tier = "Bronze"
        
    except ValueError:
        return jsonify({'error': 'Quantity must be a number'}), 400

    exp_date = None
    if 'expiration_date' in data:
        try:
            exp_date = datetime.fromisoformat(data['expiration_date'])
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

    new_donation = Donation(
        title=data['title'],
        description=data['description'],
        quantity_kg=kg_amount,
        food_type=data['food_type'],
        tags=data.get('tags', ''),
        image_url=data.get('image_url'),
        donor_id=current_user_id,
        status='available',
        expiration_date=exp_date
    )

    try:
        db.session.add(new_donation)
        db.session.commit()
        return jsonify({
            'message': f'Donation posted! You earned {points_earned} points.',
            'new_tier': user.impact_tier,
            'donation_id': new_donation.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/donations', methods=['GET'])
def get_donations():
    """
    Returns available donations.
    ✅ Distance Sorting ENABLED (Requires PostGIS from Step 2)
    """
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    results = []

    if lat and lng:
        # Create a geometry point for the rescuer
        rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        
        # Calculate distance using PostGIS
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
                'tags': donation.tags,
                'image_url': donation.image_url,
                'organization_name': donation.donor.organization_name,
                'expiration_date': donation.expiration_date,
                'distance_km': round(distance_meters / 1000, 2)
            })
        
        # Sort results by distance (closest first)
        results.sort(key=lambda x: x['distance_km'])
        
    else:
        # Fallback if no location provided
        donations = Donation.query.filter_by(status='available').all()
        for donation in donations:
            results.append({
                'id': donation.id,
                'title': donation.title,
                'description': donation.description,
                'organization_name': donation.donor.organization_name,
                'quantity_kg': donation.quantity_kg,
                'tags': donation.tags,
                'image_url': donation.image_url,
                'distance_km': None
            })

    return jsonify({'donations': results}), 200


# =======================================================
#  SECTION 5: CLAIMS & VERIFICATION
# =======================================================

@app.route('/api/claim', methods=['POST'])
@jwt_required()
def claim_donation():
    data = request.get_json()
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

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

@app.route('/api/admin/pending-users', methods=['GET'])
@jwt_required()
def get_pending_users():
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
            'verification_proof': u.verification_proof
        })

    return jsonify(output), 200

@app.route('/api/admin/verify/<int:user_id>', methods=['PATCH'])
@jwt_required()
def verify_user(user_id):
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
#  SECTION 6: HISTORY & REPORTS
# =======================================================

@app.route('/api/history', methods=['GET'])
@jwt_required()
def get_user_history():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    history = []
    
    if user.role == 'donor':
        donations = Donation.query.filter_by(donor_id=current_user_id).order_by(desc(Donation.created_at)).all()
        for d in donations:
            history.append({
                'date': d.created_at.strftime('%Y-%m-%d'),
                'title': d.title,
                'quantity_kg': d.quantity_kg,
                'food_type': d.food_type,
                'status': d.status
            })
            
    elif user.role == 'rescuer':
        claims = db.session.query(Claim, Donation).join(Donation).filter(Claim.rescuer_id == current_user_id).all()
        for claim, donation in claims:
            history.append({
                'date': claim.claimed_at.strftime('%Y-%m-%d'),
                'title': donation.title,
                'quantity_kg': donation.quantity_kg,
                'food_type': donation.food_type,
                'donor_name': donation.donor.organization_name
            })
            
    return jsonify(history), 200

@app.route('/api/report/download', methods=['GET'])
@jwt_required()
def download_report():
    """ Generates CSV report. """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    si = io.StringIO()
    cw = csv.writer(si)
    
    if user.role == 'donor':
        cw.writerow(['Date', 'Title', 'Quantity (KG)', 'Food Type', 'Status', 'Impact Points'])
        donations = Donation.query.filter_by(donor_id=current_user_id).all()
        for d in donations:
            points = int(d.quantity_kg * 10)
            cw.writerow([d.created_at.strftime('%Y-%m-%d'), d.title, d.quantity_kg, d.food_type, d.status, points])
            
    elif user.role == 'rescuer':
        cw.writerow(['Claim Date', 'Title', 'Quantity (KG)', 'Food Type', 'Donor Organization'])
        claims = db.session.query(Claim, Donation).join(Donation).filter(Claim.rescuer_id == current_user_id).all()
        for claim, donation in claims:
            cw.writerow([claim.claimed_at.strftime('%Y-%m-%d'), donation.title, donation.quantity_kg, donation.food_type, donation.donor.organization_name])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={user.organization_name}_report.csv"
    output.headers["Content-type"] = "text/csv"
    return output


# =======================================================
#  SECTION 7: MESSAGING
# =======================================================

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

# =======================================================
#  SECTION 8: DASHBOARD WIDGETS
# =======================================================

@app.route('/api/donor/stats', methods=['GET'])
@jwt_required()
def get_donor_stats():
    """ DONOR DASHBOARD: Returns quick stats. """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    my_donations_count = Donation.query.filter_by(donor_id=current_user_id).count()
    
    total_weight = db.session.query(func.sum(Donation.quantity_kg))\
        .filter_by(donor_id=current_user_id).scalar() or 0
        
    active_listings = Donation.query.filter_by(donor_id=current_user_id, status='available').count()

    return jsonify({
        'total_donations_count': my_donations_count,
        'total_kg_donated': round(total_weight, 1),
        'active_listings': active_listings,
        'points': user.points,
        'impact_tier': user.impact_tier,
        'impact_message': f"You have saved {round(total_weight, 1)}kg of food!"
    }), 200

@app.route('/api/recipient/stats', methods=['GET'])
@jwt_required()
def get_recipient_stats():
    """ RECIPIENT DASHBOARD: Returns quick stats. """
    current_user_id = get_jwt_identity()
    
    my_claims_count = Claim.query.filter_by(rescuer_id=current_user_id).count()
    
    total_rescued = db.session.query(func.sum(Donation.quantity_kg))\
        .join(Claim, Claim.donation_id == Donation.id)\
        .filter(Claim.rescuer_id == current_user_id).scalar() or 0

    return jsonify({
        'total_claims': my_claims_count,
        'total_kg_rescued': round(total_rescued, 1),
        'impact_message': f"Your NGO has distributed {round(total_rescued, 1)}kg of food."
    }), 200


# =======================================================
#  SECTION 9: UTILITIES (Refreshes & Deletes)
# =======================================================

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_user_profile():
    """ Refreshes user data on page reload. """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    return jsonify({
        'id': user.id,
        'email': user.email,
        'username': user.username,
        'role': user.role,
        'organization_name': user.organization_name,
        'registration_number': user.registration_number,
        'business_type': user.business_type,
        'is_verified': user.is_verified,
        'verification_proof': user.verification_proof,
        'points': user.points,        
        'impact_tier': user.impact_tier
    }), 200

@app.route('/api/donations/<int:donation_id>', methods=['DELETE'])
@jwt_required()
def delete_donation(donation_id):
    """ Allows Donors to delete unclaimed listings. """
    current_user_id = get_jwt_identity()
    donation = Donation.query.get(donation_id)

    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    if str(donation.donor_id) != str(current_user_id):
        return jsonify({'error': 'Unauthorized. You did not post this.'}), 403

    if donation.status != 'available':
        return jsonify({'error': 'Cannot delete. This item has already been claimed.'}), 400

    db.session.delete(donation)
    db.session.commit()
    return jsonify({'message': 'Donation deleted successfully'}), 200
import csv
import io
from flask import request, jsonify, make_response
from app import app, db, mail
from models import User, Donation, Claim, Message
from werkzeug.security import generate_password_hash, check_password_hash 
from sqlalchemy import func, desc
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta

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
    
    # -------------------------------------------------------
#  STEP 1: ADMIN MANUAL RESET (Fail-Safe)
# -------------------------------------------------------
@app.route('/api/admin/reset-password', methods=['POST'])
@jwt_required()
def admin_reset_password():
    """
    Allows the Super Admin to force-reset any user's password.
    Use this if the email system fails or for immediate support.
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)
    
    # 1. Security Check: Only Admins can do this
    if not admin or admin.role != 'admin':
        return jsonify({'error': 'Access Denied. Only Admins can reset passwords manually.'}), 403
        
    data = request.get_json()
    user_email = data.get('email')
    new_temp_password = data.get('new_password')
    
    if not user_email or not new_temp_password:
        return jsonify({'error': 'Please provide the user email and the new password.'}), 400
        
    # 2. Find the User
    user_to_fix = User.query.filter_by(email=user_email).first()
    
    if not user_to_fix:
        return jsonify({'error': 'User with that email was not found.'}), 404
        
    # 3. Update the Password
    user_to_fix.set_password(new_temp_password)
    db.session.commit()
    
    return jsonify({
        'message': f'SUCCESS! Password for {user_email} has been reset.',
        'note': 'Please tell the user to login with this new password immediately.'
    }), 200 


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
#  SECTION 3: ADMIN DASHBOARD (Detailed Drill-Downs)
# =======================================================

# 1. USERS CLICKED -> Show full list with roles
@app.route('/api/admin/users-list', methods=['GET'])
@jwt_required()
def get_all_users_detailed():
    """ 
    Called when Admin clicks the 'Total Users' card.
    Returns a list of all users, their roles, and status.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if user.role != 'admin': return jsonify({'error': 'Admins only'}), 403

    users = User.query.all()
    results = []
    
    for u in users:
        results.append({
            'id': u.id,
            'organization_name': u.organization_name,
            'email': u.email,
            'role': u.role.capitalize(), # 'Donor', 'Rescuer', 'Admin'
            'is_verified': u.is_verified,
            'points': u.points,
            'tier': u.impact_tier
        })
    
    return jsonify(results), 200


# 2. CLAIMS CLICKED -> Show history of who took what
@app.route('/api/admin/claims-log', methods=['GET'])
@jwt_required()
def get_claims_log():
    """
    Called when Admin clicks 'Claims' card.
    Shows: Date | Rescuer | Donor | Food | Weight
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if user.role != 'admin': return jsonify({'error': 'Admins only'}), 403

    # Join Claim -> Donation -> Donor & Rescuer
    claims = db.session.query(Claim, Donation, User)\
        .join(Donation, Claim.donation_id == Donation.id)\
        .join(User, Claim.rescuer_id == User.id)\
        .order_by(desc(Claim.claimed_at)).all()

    results = []
    for claim, donation, rescuer in claims:
        results.append({
            'claim_id': claim.id,
            'date': claim.claimed_at.strftime('%Y-%m-%d %H:%M'),
            'rescuer_name': rescuer.organization_name,
            'donor_name': donation.donor.organization_name,
            'food_title': donation.title,
            'weight_kg': claim.quantity_claimed,
            'status': 'Picked Up' if claim.picked_up_at else 'Pending Pickup'
        })

    return jsonify(results), 200


# 3. PENDING CLICKED -> Show waiting list (Already partially exists, but updated here)
@app.route('/api/admin/pending-list', methods=['GET'])
@jwt_required()
def get_pending_details():
    """
    Called when Admin clicks 'Pending' card.
    Shows users waiting for approval + registration date.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if user.role != 'admin': return jsonify({'error': 'Admins only'}), 403

    pending_users = User.query.filter_by(is_verified=False).all()
    results = []

    for u in pending_users:
        # Note: We don't have a 'registered_at' column in User yet, 
        # so we will just show their details.
        results.append({
            'id': u.id,
            'organization_name': u.organization_name,
            'email': u.email,
            'role': u.role,
            'registration_number': u.registration_number,
            'verification_proof': u.verification_proof
        })

    return jsonify(results), 200


# 4. FOOD RESCUED CLICKED -> Show Aggregated Stats (Rice: 30kg, etc.)
@app.route('/api/admin/food-breakdown', methods=['GET'])
@jwt_required()
def get_food_breakdown():
    """
    Called when Admin clicks 'Food Rescued' card.
    Groups claims by 'Food Type' and sums the weight.
    Example Output: {'Rice': 50, 'Beans': 20, 'Vegetables': 100}
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    if user.role != 'admin': return jsonify({'error': 'Admins only'}), 403

    # Magic SQL: Group by Food Type, Sum the Claimed Quantity
    stats = db.session.query(
        Donation.food_type, 
        func.sum(Claim.quantity_claimed)
    ).join(Claim).group_by(Donation.food_type).all()

    results = []
    total_system_weight = 0

    for food_type, total_weight in stats:
        if total_weight: # Filter out None/Zero
            val = round(total_weight, 1)
            results.append({
                'name': food_type or "Uncategorized", 
                'total_kg': val
            })
            total_system_weight += val

    # Sort so the most popular food is at the top
    results.sort(key=lambda x: x['total_kg'], reverse=True)

    return jsonify({
        'breakdown': results,
        'grand_total_kg': total_system_weight
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
        initial_quantity_kg=kg_amount,
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
    ✅ HIDES EXPIRED ITEMS automatically.
    ✅ Uses ST_Distance with GEOGRAPHY for accurate meters.
    """
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    results = []

    # Filter out expired items in Python loop for safety
    now = datetime.now()

    if lat and lng:
        rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
        
        donations_with_dist = db.session.query(
            Donation, 
            func.ST_Distance(
                func.ST_Cast(User.location, 'GEOGRAPHY'), 
                func.ST_Cast(rescuer_location, 'GEOGRAPHY')
            ).label('distance')
        ).join(User).filter(Donation.status.in_(['available', 'partially_claimed'])).all()

        for donation, distance_meters in donations_with_dist:
            # 🛑 Skip if Expired
            if donation.expiration_date and donation.expiration_date < now:
                continue

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
        
        results.sort(key=lambda x: x['distance_km'])
        
    else:
        donations = Donation.query.filter(Donation.status.in_(['available', 'partially_claimed'])).all()
        for donation in donations:
            # 🛑 Skip if Expired
            if donation.expiration_date and donation.expiration_date < now:
                continue

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
    """
    Standard Claim Logic + SAFETY CHECK.
    Prevents claiming of expired food.
    """
    data = request.get_json()
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if not user.is_verified:
        return jsonify({'error': 'Account not verified.'}), 403

    if not data.get('donation_id'):
        return jsonify({'error': 'Missing donation_id'}), 400

    donation = Donation.query.get(data['donation_id'])
    
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    # 🛑 EXPIRATION CHECK (New)
    # If there is an expiry date AND it is in the past...
    if donation.expiration_date and donation.expiration_date < datetime.now():
        return jsonify({'error': 'This donation has expired and cannot be claimed.'}), 400

    if donation.status == 'claimed':
        return jsonify({'error': 'This donation is fully claimed.'}), 400

    # --- PARTIAL CLAIM LOGIC ---
    claim_qty = float(data.get('quantity_kg', donation.quantity_kg))
    
    if claim_qty <= 0:
         return jsonify({'error': 'Quantity must be positive'}), 400
    
    # Tolerance for floating point math
    if claim_qty > donation.quantity_kg + 0.01:
        return jsonify({'error': f'Only {donation.quantity_kg}kg is available.'}), 400

    new_claim = Claim(
        donation_id=donation.id,
        rescuer_id=current_user_id,
        quantity_claimed=claim_qty
    )
    
    donation.quantity_kg -= claim_qty
    
    if donation.quantity_kg <= 0.1:
        donation.quantity_kg = 0
        donation.status = 'claimed'
        msg = "You claimed the last of this donation!"
    else:
        donation.status = 'partially_claimed'
        msg = f"You claimed {claim_qty}kg. {round(donation.quantity_kg, 1)}kg remains available."

    try:
        db.session.add(new_claim)
        db.session.commit()
        return jsonify({'message': msg}), 201
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
        # Donors see: What they posted, and how much is left
        donations = Donation.query.filter_by(donor_id=current_user_id).order_by(desc(Donation.created_at)).all()
        for d in donations:
            history.append({
                'date': d.created_at.strftime('%Y-%m-%d'),
                'title': d.title,
                'initial_qty': d.initial_quantity_kg, # What I gave
                'remaining_qty': d.quantity_kg,       # What is left
                'food_type': d.food_type,
                'status': d.status
            })
            
    elif user.role == 'rescuer':
        # Rescuers see: Exactly what THEY took (not the whole donation size)
        claims = db.session.query(Claim, Donation).join(Donation).filter(Claim.rescuer_id == current_user_id).all()
        for claim, donation in claims:
            history.append({
                'date': claim.claimed_at.strftime('%Y-%m-%d'),
                'title': donation.title,
                'quantity_claimed': claim.quantity_claimed, # <--- Specific amount
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

@app.route('/api/donations/<int:donation_id>', methods=['PUT'])
@jwt_required()
def update_donation(donation_id):
    """
    Allows a Donor to edit their listing (Title, Quantity, etc.).
    Constraint: Can only edit if the item hasn't been fully claimed yet.
    """
    current_user_id = get_jwt_identity()
    donation = Donation.query.get(donation_id)

    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    # 1. Check Ownership
    if str(donation.donor_id) != str(current_user_id):
        return jsonify({'error': 'Unauthorized. You did not post this.'}), 403

    # 2. Check Status
    if donation.status != 'available':
        return jsonify({'error': 'Cannot edit. This item is already claimed or closed.'}), 400

    data = request.get_json()

    # 3. Update Fields (Only if provided)
    if 'title' in data: donation.title = data['title']
    if 'description' in data: donation.description = data['description']
    if 'food_type' in data: donation.food_type = data['food_type']
    if 'tags' in data: donation.tags = data['tags']
    if 'image_url' in data: donation.image_url = data['image_url']
    
    # Special Logic for Quantity: Update points if quantity changes?
    # For simplicity, we just update the weight. 
    # (Advanced: You could recalculate points, but let's keep it simple for now).
    if 'quantity_kg' in data: 
        donation.quantity_kg = float(data['quantity_kg'])

    try:
        db.session.commit()
        return jsonify({'message': 'Donation updated successfully!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
    # ---------------------------------------------------------
#  FORGOT PASSWORD ROUTE
# ---------------------------------------------------------

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({"error": "Email is required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"message": "If your email exists, a reset link has been sent."}), 200

    # --- SMART DOMAIN DETECTION ---
    # 1. Get the URL of the Frontend that called this API (e.g., your preview link)
    frontend_url = request.headers.get('Origin')
    
    # 2. Fallback: If we can't detect it, use your REAL production domain
    if not frontend_url:
        frontend_url = "https://food-rescue-network.vercel.app"  # <--- UPDATED HERE

    # 3. Create the token
    reset_token = create_access_token(identity=user.id, expires_delta=timedelta(minutes=15))

    # 4. Build the dynamic link
    reset_link = f"{frontend_url}/auth/reset-password?token={reset_token}"

    try:
        msg = Message(
            subject="FRN Password Reset Request",
            recipients=[email],
            body=f"Hello,\n\nClick here to reset your password:\n{reset_link}\n\nThis link expires in 15 minutes."
        )
        mail.send(msg)
        return jsonify({"message": "Password reset email sent!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
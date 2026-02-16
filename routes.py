import csv
import io
from flask import request, jsonify, make_response, Response
from flask_mail import Message
from app import app, db, mail, socketio
from models import User, Donation, Claim, Message
from werkzeug.security import generate_password_hash, check_password_hash 
from sqlalchemy import func, desc
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
import io
from utils import log_activity
from utils import send_verification_email

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

    # 1. Security Checks
    if not user.is_verified:
        return jsonify({'error': 'Account not verified. You cannot post donations yet.'}), 403

    if user.role != 'donor':
        return jsonify({'error': 'Only Donors (Businesses) can post food.'}), 403

    data = request.get_json()
    
    # 2. Validation
    required_fields = ['title', 'description', 'quantity_kg', 'food_type']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        kg_amount = float(data['quantity_kg'])
    except ValueError:
        return jsonify({'error': 'Quantity must be a number'}), 400

    # 3. Date Handling
    exp_date = None
    if 'expiration_date' in data:
        try:
            exp_date = datetime.fromisoformat(data['expiration_date'])
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400

    # 4. Create Donation (NO POINTS AWARDED YET)
    new_donation = Donation(
        title=data['title'],
        description=data['description'],
        quantity_kg=kg_amount,
        initial_quantity_kg=kg_amount, # Important for tracking completion
        food_type=data['food_type'],
        tags=data.get('tags', ''),
        image_url=data.get('image_url'),
        donor_id=current_user_id,
        status='available', # Default status
        expiration_date=exp_date
    )

    try:
        db.session.add(new_donation)
        db.session.commit()
        
        # 5. 📝 LOG IT
        log_activity(current_user_id, "POST_DONATION", f"Posted {new_donation.title} ({new_donation.quantity_kg}kg)")
        
        # 6. ⚡ REAL-TIME UPDATE (RICH DATA TRIGGER)
        # We send the FULL DATA so the Frontend can render the card immediately.
        socketio.emit('new_donation', {
            'id': new_donation.id,
            'title': new_donation.title,
            'description': new_donation.description,
            'quantity_kg': new_donation.quantity_kg,
            'food_type': new_donation.food_type,
            'tags': new_donation.tags,
            'image_url': new_donation.image_url,
            'organization_name': user.organization_name,
            'organization_type': user.business_type, # Useful for UI badges (e.g. "Hotel")
            
            # 🕒 TIME FIELDS (Critical for "New" Badge logic)
            'created_at': new_donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'expiration_date': new_donation.expiration_date.strftime('%Y-%m-%d') if new_donation.expiration_date else None,
            
            'distance_km': None # Null because this broadcast goes to everyone
        })

        return jsonify({
            'message': 'Donation posted successfully! Points will be awarded when this item is claimed.',
            'donation_id': new_donation.id,
            'created_at': new_donation.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/donations', methods=['GET'])
def get_donations():
    """
    Returns available donations.
    ✅ HIDES EXPIRED ITEMS automatically.
    ✅ Uses ST_DistanceSphere (Crash-Proof) for accurate meters.
    ✅ Returns PRECISE TIME for 'New' badges and display.
    """
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    results = []
    
    now = datetime.now()

    # --- SCENARIO 1: LOCATION PROVIDED (Sort by Distance) ---
    if lat and lng:
        try:
            # Create point from user coordinates
            rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
            
            # Query with Distance Calculation
            query = db.session.query(
                Donation, 
                func.ST_DistanceSphere(User.location, rescuer_location).label('distance_meters')
            ).join(User).filter(Donation.status.in_(['available', 'partially_claimed']))
            
            donations_with_dist = query.all()

            for donation, distance_meters in donations_with_dist:
                # 🛑 Skip if Expired
                if donation.expiration_date and donation.expiration_date < now:
                    continue
                
                # Format Data
                results.append({
                    'id': donation.id,
                    'title': donation.title,
                    'description': donation.description,
                    'quantity_kg': donation.quantity_kg,
                    'food_type': donation.food_type,
                    'tags': donation.tags,
                    'image_url': donation.image_url,
                    'organization_name': donation.donor.organization_name,
                    'organization_type': donation.donor.business_type, # Added for UI badges
                    
                    # 🕒 TIME FIELDS (Added)
                    'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
                    
                    # Convert meters to km for display
                    'distance_km': round(distance_meters / 1000, 2) if distance_meters is not None else None
                })
            
            # Sort by nearest first
            results.sort(key=lambda x: x['distance_km'] if x['distance_km'] is not None else float('inf'))

        except Exception as e:
            # Fallback if math fails (e.g. bad coords), just return list without distance
            print(f"⚠️ Distance Error: {e}")
            # (Logic falls through to the return at the bottom)

    # --- SCENARIO 2: NO LOCATION (Just List Newest) ---
    if not results and not (lat and lng):
        donations = Donation.query.filter(Donation.status.in_(['available', 'partially_claimed'])).order_by(Donation.created_at.desc()).all()
        
        for donation in donations:
            if donation.expiration_date and donation.expiration_date < now:
                continue

            results.append({
                'id': donation.id,
                'title': donation.title,
                'description': donation.description,
                'organization_name': donation.donor.organization_name,
                'organization_type': donation.donor.business_type, # Added
                'quantity_kg': donation.quantity_kg,
                'food_type': donation.food_type,
                'tags': donation.tags,
                'image_url': donation.image_url,
                
                # 🕒 TIME FIELDS (Added)
                'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
                
                'distance_km': None # No distance calculated
            })

    return jsonify({'donations': results}), 200


# =======================================================
#  SECTION 5: CLAIMS & VERIFICATION
# =======================================================

@app.route('/api/claim', methods=['POST'])
@jwt_required()
def claim_donation():
    """
    Standard Claim Logic + SAFETY CHECK + POINTS AWARDING.
    Prevents claiming of expired food and rewards the original Donor.
    """
    data = request.get_json()
    current_user_id = get_jwt_identity()
    rescuer = User.query.get(current_user_id) # The person claiming (NGO)

    # 1. Security & Validation
    if not rescuer.is_verified:
        return jsonify({'error': 'Account not verified.'}), 403

    donation_id = data.get('donation_id')
    if not donation_id:
        return jsonify({'error': 'Missing donation_id'}), 400

    donation = db.session.get(Donation, donation_id)
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    # 2. Safety Checks (Expiration & Status)
    if donation.expiration_date and donation.expiration_date < datetime.now():
        return jsonify({'error': 'This donation has expired and cannot be claimed.'}), 400

    if donation.status == 'claimed':
        return jsonify({'error': 'This donation is fully claimed.'}), 400

    # 3. Partial Claim Logic
    # Default to taking everything if no quantity specified
    claim_qty = float(data.get('quantity_kg', donation.quantity_kg))
    
    if claim_qty <= 0:
         return jsonify({'error': 'Quantity must be positive'}), 400
    
    # Tolerance for floating point math
    if claim_qty > donation.quantity_kg + 0.01:
        return jsonify({'error': f'Only {donation.quantity_kg}kg is available.'}), 400

    # 4. Process the Transaction
    donation.quantity_kg -= claim_qty
    
    # Update Status based on remaining quantity
    status_msg = ""
    if donation.quantity_kg <= 0.1:
        donation.quantity_kg = 0
        donation.status = 'claimed'
        status_msg = "You claimed the last of this donation!"
    else:
        donation.status = 'partially_claimed'
        status_msg = f"You claimed {claim_qty}kg. {round(donation.quantity_kg, 1)}kg remains available."

    # 5. Create History Record
    new_claim = Claim(
        donation_id=donation.id,
        rescuer_id=current_user_id,
        quantity_claimed=claim_qty, # Changed to match your model field name usually 'quantity_kg' or 'quantity_claimed'
        claim_date=datetime.utcnow()
    )
    new_claim.generate_code()
    
    try:
        # --- POINTS AWARDING LOGIC (The New Part) ---
        # Find the original Donor
        donor = User.query.get(donation.donor_id)
        
        # Calculate Points (1kg = 10 Points)
        points_earned = int(claim_qty * 10)
        donor.points += points_earned
        
        # Update Donor's Impact Tier
        if donor.points >= 5000: donor.impact_tier = "Sapphire"
        elif donor.points >= 2000: donor.impact_tier = "Gold"
        elif donor.points >= 500: donor.impact_tier = "Silver"
        else: donor.impact_tier = "Bronze"

        # Save everything (Claim + Donation Update + Donor Points)
        db.session.add(new_claim)
        db.session.commit()
        
       # 2. 📝 LOG IT (Who claimed what)
        log_activity(rescuer.id, "CLAIM_ITEM", f"Claimed {claim_qty}kg of {donation.title} from {donation.donor.organization_name}")

        # 3. 📧 SEND EMAILS (Notifications)
        # Email to Donor
        msg_donor = Message(f"Someone claimed your food!", recipients=[donation.donor.email])
        msg_donor.body = f"Hello {donation.donor.organization_name},\n\n{rescuer.organization_name} just claimed {claim_qty}kg of your {donation.title}.\n\nPickup Code: {new_claim.pickup_code}\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        mail.send(msg_donor)

        # Email to Rescuer
        msg_rescuer = Message(f"Claim Confirmed: {donation.title}", recipients=[rescuer.email])
        msg_rescuer.body = f"Hello {rescuer.organization_name},\n\nYou successfully claimed {claim_qty}kg.\n\nPickup Address: {donation.donor.location}\nPickup Code: {new_claim.pickup_code}\n\nShow this code to the donor upon arrival."
        mail.send(msg_rescuer)

        # 4. 🔔 REAL-TIME NOTIFICATION (Socket)
        socketio.emit('notification', {
            'user_id': donation.donor_id,
            'message': f"{rescuer.organization_name} just claimed {claim_qty}kg of {donation.title}!"
        })

        # 5. Return Response with PRECISE TIME
        return jsonify({
            'message': 'Claim successful!',
            'pickup_code': new_claim.pickup_code,
            'claimed_at': new_claim.claimed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'donor_organization': donation.donor.organization_name
        }), 201

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


@app.route('/api/admin/verify/<int:user_id>', methods=['PATCH', 'POST']) # <--- Accept BOTH methods
@jwt_required()
def verify_user(user_id):
    """
    Manually verifies a user (Admin only).
    Works with both PATCH and POST to prevent frontend errors.
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)

    # 1. Admin Security Check
    if not admin or admin.role != 'admin':
        return jsonify({'error': 'Unauthorized. Admin access required.'}), 403

    # 2. Find the User
    user_to_verify = User.query.get(user_id)
    if not user_to_verify:
        return jsonify({'error': 'User not found.'}), 404

    # 3. Flip the Switch
    try:
        user_to_verify.is_verified = True
        db.session.commit()
        return jsonify({
            'message': f'User {user_to_verify.organization_name} has been verified successfully!',
            'user_id': user_to_verify.id,
            'status': 'verified'
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

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
    """ 
    Generates CSV report based on User Role.
    - Donors: Granular view of who claimed what and exactly when.
    - Rescuers: History of their claims with Pickup Codes.
    - Admins: System-wide overview.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    # Create the in-memory string buffer
    si = io.StringIO()
    cw = csv.writer(si)
    
    # --- LOGIC FOR DONORS ---
    if user.role == 'donor':
        # Header: Expanded to show specific claim details
        cw.writerow([
            'Date Posted', 'Time Posted', 'Title', 'Food Type', 
            'Initial Qty (kg)', 'Remaining Qty (kg)', 'Status', 
            'Claimed By', 'Qty Claimed (kg)', 'Time Claimed', 'Pickup Code', 'Points Impact'
        ])
        
        # Get all donations by this donor
        donations = Donation.query.filter_by(donor_id=current_user_id).order_by(Donation.created_at.desc()).all()
        
        for d in donations:
            # Safe Fallback for Initial Quantity
            initial = getattr(d, 'initial_quantity_kg', d.quantity_kg)
            remaining = d.quantity_kg
            
            # Format Post Time
            date_posted = d.created_at.strftime('%Y-%m-%d')
            time_posted = d.created_at.strftime('%H:%M:%S')
            
            # Get specific claims for this donation to show granular history
            claims = Claim.query.filter_by(donation_id=d.id).all()
            
            if claims:
                # Scenario A: Items have been claimed (Partial or Full)
                for c in claims:
                    # Fetch Rescuer Name safely
                    rescuer = User.query.get(c.rescuer_id)
                    rescuer_name = rescuer.organization_name if rescuer else "Unknown Rescuer"
                    
                    # Calculate points for this specific claim transaction
                    points = int(c.quantity_claimed * 10)
                    
                    # Format Claim Time safely
                    claim_time_str = c.claimed_at.strftime('%Y-%m-%d %H:%M:%S') if c.claimed_at else "N/A"
                    
                    cw.writerow([
                        date_posted,
                        time_posted,
                        d.title,
                        d.food_type,
                        initial,
                        remaining, # Current remaining stock
                        d.status.upper(),
                        rescuer_name,      # Who took it
                        c.quantity_claimed, # How much they took
                        claim_time_str,    # Exactly when
                        c.pickup_code,     # Security Code
                        points
                    ])
            else:
                # Scenario B: No one has claimed it yet (Show the open donation)
                cw.writerow([
                    date_posted,
                    time_posted,
                    d.title,
                    d.food_type,
                    initial,
                    remaining,
                    d.status.upper(),
                    "N/A", # No claimer
                    0,     # 0 claimed
                    "N/A", # No time
                    "N/A", # No code
                    0      # 0 points
                ])

    # --- LOGIC FOR RESCUERS ---
    elif user.role == 'rescuer':
        # Header: Added Time and Pickup Code
        cw.writerow(['Claim Date', 'Time Claimed', 'Item Title', 'Quantity Claimed (kg)', 'Food Type', 'Donor Organization', 'Pickup Code', 'Status'])
        
        # Query Claims directly
        claims = Claim.query.filter_by(rescuer_id=current_user_id).order_by(Claim.claimed_at.desc()).all()
        
        for claim in claims:
            # Get parent donation
            parent_donation = Donation.query.get(claim.donation_id)
            
            # Safe fallbacks if donation was deleted
            title = parent_donation.title if parent_donation else "Deleted Item"
            food_type = parent_donation.food_type if parent_donation else "N/A"
            donor_name = parent_donation.donor.organization_name if (parent_donation and parent_donation.donor) else "Unknown"
            current_status = parent_donation.status if parent_donation else "Unknown"
            
            # Format Time
            date_claimed = claim.claimed_at.strftime('%Y-%m-%d') if claim.claimed_at else "N/A"
            time_claimed = claim.claimed_at.strftime('%H:%M:%S') if claim.claimed_at else "N/A"

            cw.writerow([
                date_claimed,
                time_claimed,
                title,
                claim.quantity_claimed,
                food_type,
                donor_name,
                claim.pickup_code, # Vital for pickup
                current_status
            ])

    # --- LOGIC FOR ADMINS ---
    elif user.role == 'admin':
        # Admin gets the "God View"
        cw.writerow(['Date Posted', 'Time Posted', 'Donor Org', 'Title', 'Initial (kg)', 'Remaining (kg)', 'Status', 'Total Claims'])
        
        all_donations = Donation.query.order_by(Donation.created_at.desc()).all()
        
        for d in all_donations:
            claim_count = Claim.query.filter_by(donation_id=d.id).count()
            initial = getattr(d, 'initial_quantity_kg', d.quantity_kg)
            
            cw.writerow([
                d.created_at.strftime('%Y-%m-%d'),
                d.created_at.strftime('%H:%M:%S'),
                d.donor.organization_name,
                d.title,
                initial,
                d.quantity_kg,
                d.status.upper(),
                claim_count
            ])

    # Final Response Construction
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename={user.role}_{user.organization_name}_report.csv"
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
    donation = db.session.get(Donation, donation_id)

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
    donation = db.session.get(Donation, donation_id)

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
    
    # --- 1. USER SELF-DELETE (With Password Guard) ---
@app.route('/api/delete-account', methods=['DELETE'])
@jwt_required()
def delete_own_account():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    data = request.get_json()
    password = data.get('password')

    if not password:
        return jsonify({'error': 'Password is required to confirm deletion.'}), 400

    # 🛑 SECURITY CHECK: Must confirm password to delete
    if not user.check_password(password):
        return jsonify({'error': 'Incorrect password. Account NOT deleted.'}), 403

    try:
        # Optional: Log this event before deleting
        print(f"⚠️ USER DELETING ACCOUNT: {user.email}")
        
        db.session.delete(user)
        db.session.commit()
        return jsonify({'message': 'Your account has been permanently deleted.'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
def admin_delete_user(user_id):
    """
    Secure Admin Deletion.
    Requires the Admin to send the target user's email to confirm.
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)

    # 1. Governance Check: Only Admins
    if not admin or admin.role != 'admin':
        return jsonify({'error': 'Unauthorized. Admin access required.'}), 403

    # 2. Find the Target
    user_to_delete = User.query.get(user_id)
    if not user_to_delete:
        return jsonify({'error': 'User not found.'}), 404

    # 3. Safety Check: Prevent Admin Suicide
    if user_to_delete.id == admin.id:
        return jsonify({'error': 'Safety Protocol: You cannot delete your own admin account.'}), 400

    # 4. THE CONFIRMATION CHECK (The Fix for your concern)
    # The Admin MUST send {"confirmation_email": "user@email.com"}
    data = request.get_json()
    confirmation_email = data.get('confirmation_email')

    if not confirmation_email:
        return jsonify({'error': 'Confirmation required. Please provide the user email.'}), 400

    if confirmation_email.lower() != user_to_delete.email.lower():
        return jsonify({'error': 'Mismatch! The email provided does not match the user you are trying to delete.'}), 400

    # 5. Execute Deletion
    try:
        # (Optional) Archive them instead of deleting? For now, we hard delete as requested.
        db.session.delete(user_to_delete)
        db.session.commit()
        return jsonify({
            'message': f'User {user_to_delete.email} has been permanently deleted.',
            'id': user_id
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/admin/search', methods=['GET'])
@jwt_required()
def search_users():
    """
    Allows Admins to find a user by Email or Organization Name.
    Usage: /api/admin/search?q=bakery
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)

    if admin.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    query = request.args.get('q', '')
    if not query:
        return jsonify({'error': 'Search query required'}), 400

    # Search Logic (Case Insensitive)
    results = User.query.filter(
        (User.email.ilike(f"%{query}%")) | 
        (User.organization_name.ilike(f"%{query}%"))
    ).all()

    return jsonify([
        {
            'id': u.id,
            'email': u.email,
            'organization_name': u.organization_name,
            'role': u.role,
            'is_verified': u.is_verified
        } for u in results
    ]), 200
    
@app.route('/api/donations/<int:donation_id>', methods=['GET'])
@jwt_required(optional=True) # Optional so users can share links with non-users (preview mode)
def get_single_donation(donation_id):
    """
    Fetches full details for a single donation card.
    ✅ Calculates exact distance if user location is provided.
    ✅ Returns 'is_owner' flag so frontend can show Edit/Delete buttons.
    ✅ Returns formatted timestamps.
    """
    current_user_id = get_jwt_identity()
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    # 1. Fetch the Donation
    donation = db.session.get(Donation, donation_id)
    
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    # 2. Real-World Logic: Expired or Claimed?
    # In a real app, you don't hide it (404) if it's expired; you show it with a "CLOSED" badge.
    is_expired = False
    if donation.expiration_date and donation.expiration_date < datetime.now():
        is_expired = True

    # 3. Calculate Distance (if coords provided)
    distance_km = None
    if lat and lng:
        try:
            # We run a lightweight query just to get the distance for this specific item
            user_point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
            
            # Query User (Donor) location vs User (Rescuer) point
            dist = db.session.query(
                func.ST_DistanceSphere(User.location, user_point)
            ).filter(User.id == donation.donor_id).scalar()
            
            if dist is not None:
                distance_km = round(dist / 1000, 2)
        except Exception:
            distance_km = None # Fail gracefully if math breaks

    # 4. Construct the Rich Response
    return jsonify({
        'id': donation.id,
        'title': donation.title,
        'description': donation.description,
        'quantity_kg': donation.quantity_kg,
        'initial_quantity_kg': getattr(donation, 'initial_quantity_kg', donation.quantity_kg),
        'food_type': donation.food_type,
        'tags': donation.tags,
        'image_url': donation.image_url,
        'status': 'expired' if is_expired else donation.status, # Override status for display
        
        # 🕒 TIME FIELDS (Consistent Format)
        'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
        
        # 📍 LOCATION & DISTANCE
        'distance_km': distance_km,
        'donor_location': donation.donor.location, # Raw string if needed for maps
        
        # 🏢 DONOR PROFILE (Trust Signals)
        'organization_name': donation.donor.organization_name,
        'organization_type': donation.donor.business_type,
        'donor_verified': donation.donor.is_verified,
        'donor_tier': getattr(donation.donor, 'impact_tier', 'Bronze'), # Gamification badge
        
        # 🛠️ UTILITY (For Frontend Logic)
        'is_owner': current_user_id == donation.donor_id # True if YOU posted this
    }), 200    
    
@app.route('/api/certificate/download', methods=['GET'])
@jwt_required()
def download_tax_certificate():
    """
    Generates an Official Donation Certificate (PDF).
    Calculates total KG claimed from this Donor and certifies it.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)

    if user.role != 'donor':
        return jsonify({'error': 'Only Donors can generate tax certificates.'}), 403

    # 1. CALCULATE TOTAL IMPACT
    # We sum up the 'quantity_claimed' from all claims made on this donor's posts.
    # We only certify food that was ACTUALLY claimed (not just posted).
    total_kg = db.session.query(func.sum(Claim.quantity_claimed))\
        .join(Donation)\
        .filter(Donation.donor_id == user.id)\
        .scalar() or 0.0

    if total_kg == 0:
        return jsonify({'error': 'No completed donations found yet to certify.'}), 400

    # 2. GENERATE PDF IN MEMORY
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # --- PDF DESIGN ---
    # Header
    p.setFont("Helvetica-Bold", 24)
    p.drawCentredString(width / 2, height - 100, "CERTIFICATE OF DONATION")
    
    p.setFont("Helvetica", 12)
    p.drawCentredString(width / 2, height - 130, "Food Rescue Network Nigeria")
    
    # Border
    p.setStrokeColor(colors.green)
    p.setLineWidth(3)
    p.rect(50, 50, width - 100, height - 100)

    # Content
    p.setFont("Helvetica", 14)
    text_y = height - 250
    
    content = [
        f"This certificate is proudly presented to:",
        f"",
        f"{user.organization_name.upper()}",
        f"",
        f"In recognition of your invaluable contribution to fighting hunger.",
        f"Through your partnership with FRN, you have successfully donated:",
        f"",
        f"{round(total_kg, 2)} KG of Food",
        f"",
        f"Date Generated: {datetime.now().strftime('%Y-%m-%d')}",
        f"Registration No: {user.registration_number if user.registration_number else 'N/A'}"
    ]

    for line in content:
        p.drawCentredString(width / 2, text_y, line)
        text_y -= 25  # Move down for next line

    # Signature Area
    p.setLineWidth(1)
    p.line(width / 2 - 100, 150, width / 2 + 100, 150)
    p.setFont("Helvetica-Oblique", 10)
    p.drawCentredString(width / 2, 135, "Authorized Signature - FRN Admin")

    # Finalize
    p.showPage()
    p.save()
    
    buffer.seek(0)
    
    return Response(
        buffer,
        mimetype='application/pdf',
        headers={"Content-Disposition": f"attachment;filename=FRN_Certificate_{datetime.now().year}.pdf"}
    )    
    
    
@app.route('/api/donations/<int:donation_id>', methods=['GET'])
@jwt_required(optional=True) # Optional so users can share links with non-users (preview mode)
def get_single_donation(donation_id):
    """
    Fetches full details for a single donation card.
    ✅ Calculates exact distance if user location is provided.
    ✅ Returns 'is_owner' flag so frontend can show Edit/Delete buttons.
    ✅ Returns formatted timestamps.
    """
    current_user_id = get_jwt_identity()
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    # 1. Fetch the Donation
    donation = db.session.get(Donation, donation_id)
    
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    # 2. Real-World Logic: Expired or Claimed?
    # In a real app, you don't hide it (404) if it's expired; you show it with a "CLOSED" badge.
    is_expired = False
    if donation.expiration_date and donation.expiration_date < datetime.now():
        is_expired = True

    # 3. Calculate Distance (if coords provided)
    distance_km = None
    if lat and lng:
        try:
            # We run a lightweight query just to get the distance for this specific item
            user_point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
            
            # Query User (Donor) location vs User (Rescuer) point
            dist = db.session.query(
                func.ST_DistanceSphere(User.location, user_point)
            ).filter(User.id == donation.donor_id).scalar()
            
            if dist is not None:
                distance_km = round(dist / 1000, 2)
        except Exception:
            distance_km = None # Fail gracefully if math breaks

    # 4. Construct the Rich Response
    return jsonify({
        'id': donation.id,
        'title': donation.title,
        'description': donation.description,
        'quantity_kg': donation.quantity_kg,
        'initial_quantity_kg': getattr(donation, 'initial_quantity_kg', donation.quantity_kg),
        'food_type': donation.food_type,
        'tags': donation.tags,
        'image_url': donation.image_url,
        'status': 'expired' if is_expired else donation.status, # Override status for display
        
        # 🕒 TIME FIELDS (Consistent Format)
        'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
        
        # 📍 LOCATION & DISTANCE
        'distance_km': distance_km,
        'donor_location': donation.donor.location, # Raw string if needed for maps
        
        # 🏢 DONOR PROFILE (Trust Signals)
        'organization_name': donation.donor.organization_name,
        'organization_type': donation.donor.business_type,
        'donor_verified': donation.donor.is_verified,
        'donor_tier': getattr(donation.donor, 'impact_tier', 'Bronze'), # Gamification badge
        
        # 🛠️ UTILITY (For Frontend Logic)
        'is_owner': current_user_id == donation.donor_id # True if YOU posted this
    }), 200    
    
@app.route('/api/users/history', methods=['GET'])
@jwt_required()
def get_user_history():
    """
    Returns classified history for tabs: 'active' vs 'history'.
    """
    # 1. CLEANUP FIRST (Mark old items as expired)
    update_expired_status()

    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    results = {
        'active': [],   # For the "Live" tab
        'history': []   # For the "Past" tab (Claimed/Expired)
    }

    # --- DONOR LOGIC ---
    if user.role in ['donor', 'individual']:
        donations = Donation.query.filter_by(donor_id=current_user_id).order_by(Donation.created_at.desc()).all()

        for d in donations:
            initial = getattr(d, 'initial_quantity_kg', d.quantity_kg)
            # Calculate progress
            claimed = initial - d.quantity_kg
            progress = int((claimed / initial) * 100) if initial > 0 else 0

            item = {
                'id': d.id,
                'title': d.title,
                'quantity_posted': initial,
                'quantity_remaining': d.quantity_kg,
                'status': d.status, # 'available', 'partially_claimed', 'claimed', 'expired'
                'created_at': d.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'image_url': parent.image_url if parent else None,
                'progress_percent': progress
            }

            # SORTING INTO TABS
            if d.status in ['available', 'partially_claimed']:
                results['active'].append(item)
            else:
                # 'claimed' or 'expired' goes to history
                results['history'].append(item)

    # --- RESCUER LOGIC ---
    elif user.role == 'rescuer':
        claims = Claim.query.filter_by(rescuer_id=current_user_id).order_by(Claim.claimed_at.desc()).all()
        
        for c in claims:
            parent = Donation.query.get(c.donation_id)
            item = {
                'id': c.id,
                'title': parent.title if parent else "Deleted Item",
                'quantity': c.quantity_claimed,
                'pickup_code': c.pickup_code,
                'status': c.status, # 'pending_pickup', 'completed'
                'date': c.claimed_at.strftime('%Y-%m-%d'),
                'image_url': parent.image_url if parent else None
            }
            
            if c.status == 'pending_pickup':
                results['active'].append(item)
            else:
                results['history'].append(item)

    return jsonify(results), 200    

@app.route('/api/auth/register-individual', methods=['POST'])
def register_individual():
    data = request.get_json()
    
    # Validation
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400

    # Create User (Storing "John Doe" in 'organization_name')
    new_user = User(
        email=data['email'],
        organization_name=data['full_name'], # <--- This works perfectly!
        business_type='individual',
        role='individual',
        location=data['location'],
        phone_number=data['phone'],
        is_verified=False 
    )
    new_user.set_password(data['password'])

    try:
        db.session.add(new_user)
        db.session.commit()
        
        # Send the Email
        send_verification_email(new_user)
        
        return jsonify({
            'message': 'Registration successful! Check your email to verify account.'
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# 2. VERIFY EMAIL (The Link User Clicks)
@app.route('/api/auth/verify-email/<token>', methods=['GET'])
def verify_email(token):
    user = User.verify_token(token)
    
    if not user:
        return jsonify({'error': 'Invalid or expired token.'}), 400
        
    if user.is_verified:
        return jsonify({'message': 'Account already verified.'}), 200

    user.is_verified = True
    db.session.commit()
    
    return jsonify({'message': 'Email verified! You can now log in.'}), 200

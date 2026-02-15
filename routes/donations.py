from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func, desc
from datetime import datetime
from models import Watchlist, db, User, Donation, Claim
from extensions import socketio, mail
from flask_mail import Message
from utils import log_activity

donations_bp = Blueprint('donations', __name__)

# ==========================================
#  1. CREATE DONATION
# ==========================================
@donations_bp.route('/api/donations', methods=['POST'])
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

    # 4. Create Object
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
        
        # 5. Log & Socket
        log_activity(current_user_id, "POST_DONATION", f"Posted {new_donation.title} ({new_donation.quantity_kg}kg)")
        
        socketio.emit('new_donation', {
            'id': new_donation.id,
            'title': new_donation.title,
            'description': new_donation.description,
            'quantity_kg': new_donation.quantity_kg,
            'food_type': new_donation.food_type,
            'tags': new_donation.tags,
            'image_url': new_donation.image_url,
            'organization_name': user.organization_name,
            'organization_type': user.business_type,
            'created_at': new_donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'expiration_date': new_donation.expiration_date.strftime('%Y-%m-%d') if new_donation.expiration_date else None,
            'distance_km': None
        })

        # 6. 🔔 WATCHLIST ALERTS (Integrated Logic)
        # Find everyone watching this specific Food Type
        interested_users = Watchlist.query.filter_by(food_type=new_donation.food_type).all()

        if interested_users:
            print(f"🔔 Found {len(interested_users)} users watching {new_donation.food_type}")
            
            for watch_item in interested_users:
                # Don't alert the person who posted it!
                if str(watch_item.user_id) == str(current_user_id):
                    continue
                    
                try:
                    # Send Email
                    msg = Message(f"ALERT: {new_donation.food_type} Available Now!",
                                  recipients=[watch_item.user.email])
                    
                    msg.body = f"""Hello {watch_item.user.organization_name},

Good news! A new donation matching your watchlist for '{new_donation.food_type}' was just posted.

Item: {new_donation.title}
Quantity: {new_donation.quantity_kg}kg
Location: {user.organization_name}

Login now to claim it before it's gone!
"""
                    mail.send(msg)
                except Exception as e:
                    # We catch errors here so the donation post SUCCEEDS even if one email fails
                    print(f"⚠️ Failed to send alert to {watch_item.user.email}: {e}")

        # 7. Final Success Response
        return jsonify({
            'message': 'Donation posted successfully!',
            'donation_id': new_donation.id,
            'created_at': new_donation.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
#  2. GET ALL DONATIONS (Feed)
# ==========================================
@donations_bp.route('/api/donations', methods=['GET'])
def get_donations():
    """
    Returns available donations.
    ✅ Includes Distance for ALL items if lat/lng is provided.
    """
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    results = []
    
    now = datetime.now()

    # --- SCENARIO 1: LOCATION PROVIDED (Sort by Distance) ---
    if lat and lng:
        try:
            rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
            
            # Complex Query: Get Donation + Calculated Distance
            query = db.session.query(
                Donation, 
                func.ST_DistanceSphere(User.location, rescuer_location).label('distance_meters')
            ).join(User).filter(Donation.status.in_(['available', 'partially_claimed']))
            
            donations_with_dist = query.all()

            for donation, distance_meters in donations_with_dist:
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
                    'organization_type': donation.donor.business_type,
                    'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
                    # Distance
                    'distance_km': round(distance_meters / 1000, 2) if distance_meters is not None else None
                })
            
            # Sort by nearest
            results.sort(key=lambda x: x['distance_km'] if x['distance_km'] is not None else float('inf'))

        except Exception as e:
            print(f"⚠️ Distance Error: {e}")
            # Fallback handled below

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
                'organization_type': donation.donor.business_type,
                'quantity_kg': donation.quantity_kg,
                'food_type': donation.food_type,
                'tags': donation.tags,
                'image_url': donation.image_url,
                'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
                'distance_km': None
            })

    return jsonify({'donations': results}), 200


# ==========================================
#  3. GET SINGLE DONATION
# ==========================================
@donations_bp.route('/api/donations/<int:donation_id>', methods=['GET'])
@jwt_required(optional=True)
def get_single_donation(donation_id):
    """
    Fetches full details for a single donation card.
    ✅ Includes Distance Calculation.
    """
    current_user_id = get_jwt_identity()
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    donation = Donation.query.get(donation_id)
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    is_expired = False
    if donation.expiration_date and donation.expiration_date < datetime.now():
        is_expired = True

    # Distance
    distance_km = None
    if lat and lng:
        try:
            user_point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
            dist = db.session.query(
                func.ST_DistanceSphere(User.location, user_point)
            ).filter(User.id == donation.donor_id).scalar()
            
            if dist is not None:
                distance_km = round(dist / 1000, 2)
        except Exception:
            distance_km = None

    return jsonify({
        'id': donation.id,
        'title': donation.title,
        'description': donation.description,
        'quantity_kg': donation.quantity_kg,
        'initial_quantity_kg': getattr(donation, 'initial_quantity_kg', donation.quantity_kg),
        'food_type': donation.food_type,
        'tags': donation.tags,
        'image_url': donation.image_url,
        'status': 'expired' if is_expired else donation.status,
        'created_at': donation.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'expiration_date': donation.expiration_date.strftime('%Y-%m-%d') if donation.expiration_date else None,
        'distance_km': distance_km,
        'donor_location': donation.donor.location, # Raw string (useful for debugging)
        'organization_name': donation.donor.organization_name,
        'organization_type': donation.donor.business_type,
        'donor_verified': donation.donor.is_verified,
        'donor_tier': getattr(donation.donor, 'impact_tier', 'Bronze'),
        'is_owner': str(current_user_id) == str(donation.donor_id)
    }), 200


# ==========================================
#  4. GET SIMILAR DONATIONS (Discovery)
# ==========================================
@donations_bp.route('/api/donations/similar/<int:donation_id>', methods=['GET'])
@jwt_required()
def get_similar_donations(donation_id):
    """
    Finds other available donations with the same Food Type.
    ✅ Includes Distance Calculation.
    """
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    
    original = Donation.query.get(donation_id)
    if not original:
        return jsonify({'error': 'Donation not found'}), 404

    results = []
    
    # Try calculating distance if coords are present
    if lat and lng:
        try:
            rescuer_location = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
            
            similar_items = db.session.query(
                Donation,
                func.ST_DistanceSphere(User.location, rescuer_location).label('distance_meters')
            ).join(User).filter(
                Donation.food_type == original.food_type,
                Donation.status == 'available',
                Donation.id != original.id
            ).order_by(Donation.created_at.desc()).limit(3).all()
            
            for d, dist in similar_items:
                results.append({
                    'id': d.id,
                    'title': d.title,
                    'quantity_kg': d.quantity_kg,
                    'organization_name': d.donor.organization_name,
                    'image_url': d.image_url,
                    'distance_km': round(dist / 1000, 2) if dist is not None else None
                })
        except Exception:
             pass # Fallback to normal query below

    # Fallback (No location or calculation failed)
    if not results:
        similar_items = Donation.query.filter(
            Donation.food_type == original.food_type,
            Donation.status == 'available',
            Donation.id != original.id
        ).order_by(Donation.created_at.desc()).limit(3).all()

        for d in similar_items:
             results.append({
                'id': d.id,
                'title': d.title,
                'quantity_kg': d.quantity_kg,
                'organization_name': d.donor.organization_name,
                'image_url': d.image_url,
                'distance_km': None
            })

    return jsonify({'similar': results}), 200


# ==========================================
#  5. CLAIM DONATION
# ==========================================
@donations_bp.route('/api/claim', methods=['POST'])
@jwt_required()
def claim_donation():
    """
    Standard Claim Logic + SAFETY CHECK + POINTS AWARDING.
    Prevents claiming of expired food and rewards the original Donor.
    """
    data = request.get_json()
    current_user_id = get_jwt_identity()
    rescuer = User.query.get(current_user_id) 

    # 1. Security & Validation
    if rescuer.role != 'rescuer':
        return jsonify({'error': 'Only registered NGOs/Rescuers can claim food.'}), 403
    
    if not rescuer.is_verified:
        return jsonify({'error': 'Account not verified.'}), 403

    donation_id = data.get('donation_id')
    if not donation_id:
        return jsonify({'error': 'Missing donation_id'}), 400

    donation = Donation.query.get(donation_id)
    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    # 2. Safety Checks
    if donation.expiration_date and donation.expiration_date < datetime.now():
        return jsonify({'error': 'This donation has expired and cannot be claimed.'}), 400

    if donation.status == 'claimed':
        return jsonify({'error': 'This donation is fully claimed.'}), 400

    # 3. Partial Claim Logic
    claim_qty = float(data.get('quantity_kg', donation.quantity_kg))
    
    if claim_qty <= 0:
         return jsonify({'error': 'Quantity must be positive'}), 400
    
    if claim_qty > donation.quantity_kg + 0.01:
        return jsonify({'error': f'Only {donation.quantity_kg}kg is available.'}), 400

    # 4. Process the Transaction
    donation.quantity_kg -= claim_qty
    
    if donation.quantity_kg <= 0.1:
        donation.quantity_kg = 0
        donation.status = 'claimed'
    else:
        donation.status = 'partially_claimed'

    # 5. Create History Record
    new_claim = Claim(
        donation_id=donation.id,
        rescuer_id=current_user_id,
        quantity_claimed=claim_qty
    )
    new_claim.generate_code()
    
    try:
        # --- POINTS AWARDING LOGIC ---
        donor = User.query.get(donation.donor_id)
        points_earned = int(claim_qty * 10)
        donor.points += points_earned
        
        # Update Donor's Impact Tier
        if donor.points >= 5000: donor.impact_tier = "Sapphire"
        elif donor.points >= 2000: donor.impact_tier = "Gold"
        elif donor.points >= 500: donor.impact_tier = "Silver"
        else: donor.impact_tier = "Bronze"

        db.session.add(new_claim)
        db.session.commit()
        
        # Log, Email, Socket
        log_activity(rescuer.id, "CLAIM_ITEM", f"Claimed {claim_qty}kg of {donation.title}")

        # Email Donor
        try:
            msg_donor = Message(f"Someone claimed your food!", recipients=[donation.donor.email])
            msg_donor.body = f"Hello {donation.donor.organization_name},\n\n{rescuer.organization_name} just claimed {claim_qty}kg of your {donation.title}.\n\nPickup Code: {new_claim.pickup_code}"
            mail.send(msg_donor)
        except: pass # Don't crash if mail fails

        # Email Rescuer
        try:
            msg_rescuer = Message(f"Claim Confirmed: {donation.title}", recipients=[rescuer.email])
            msg_rescuer.body = f"Hello {rescuer.organization_name},\n\nYou successfully claimed {claim_qty}kg.\n\nPickup Code: {new_claim.pickup_code}"
            mail.send(msg_rescuer)
        except: pass

        socketio.emit('notification', {
            'user_id': donation.donor_id,
            'message': f"{rescuer.organization_name} just claimed {claim_qty}kg of {donation.title}!"
        })

        return jsonify({
            'message': 'Claim successful!',
            'pickup_code': new_claim.pickup_code,
            'claimed_at': new_claim.claimed_at.strftime('%Y-%m-%d %H:%M:%S'),
            'donor_organization': donation.donor.organization_name
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
#  6. DELETE DONATION
# ==========================================
@donations_bp.route('/api/donations/<int:donation_id>', methods=['DELETE'])
@jwt_required()
def delete_donation(donation_id):
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


# ==========================================
#  7. UPDATE DONATION
# ==========================================
@donations_bp.route('/api/donations/<int:donation_id>', methods=['PUT'])
@jwt_required()
def update_donation(donation_id):
    current_user_id = get_jwt_identity()
    donation = Donation.query.get(donation_id)

    if not donation:
        return jsonify({'error': 'Donation not found'}), 404

    if str(donation.donor_id) != str(current_user_id):
        return jsonify({'error': 'Unauthorized. You did not post this.'}), 403

    if donation.status != 'available':
        return jsonify({'error': 'Cannot edit. This item is already claimed or closed.'}), 400

    data = request.get_json()

    if 'title' in data: donation.title = data['title']
    if 'description' in data: donation.description = data['description']
    if 'food_type' in data: donation.food_type = data['food_type']
    if 'tags' in data: donation.tags = data['tags']
    if 'image_url' in data: donation.image_url = data['image_url']
    if 'quantity_kg' in data: donation.quantity_kg = float(data['quantity_kg'])

    try:
        db.session.commit()
        return jsonify({'message': 'Donation updated successfully!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
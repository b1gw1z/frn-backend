from flask import Blueprint, request, jsonify, Response, make_response
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import desc, func
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
import io, csv
from datetime import datetime
from models import db, User, Donation, Claim, Watchlist
from utils import log_activity, update_expired_status

user_bp = Blueprint('user', __name__)


@user_bp.route('/api/profile', methods=['GET'])
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

@user_bp.route('/api/users/history', methods=['GET'])
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

@user_bp.route('/api/user/public-profile/<int:user_id>', methods=['GET'])
@jwt_required()
def get_public_profile(user_id):
    """
    Fetches the public reputation and active listings of a donor.
    Used when a user clicks on a donor's name in the feed.
    """
    # 1. Fetch the Donor
    target_user = User.query.get(user_id)
    
    if not target_user:
        return jsonify({'error': 'User not found'}), 404

    # 2. Calculate Reputation Stats
    # (We calculate this live to ensure it's always accurate)
    total_donated_kg = db.session.query(func.sum(Donation.quantity_kg))\
        .filter(Donation.donor_id == user_id, Donation.status == 'claimed')\
        .scalar() or 0.0
    
    donation_count = Donation.query.filter_by(donor_id=user_id).count()

    # 3. Fetch ONLY Active Listings (So rescuers can claim more from them)
    active_donations = Donation.query.filter_by(donor_id=user_id, status='available')\
        .order_by(Donation.created_at.desc()).limit(5).all()
        
    active_list = []
    for d in active_donations:
        active_list.append({
            'id': d.id,
            'title': d.title,
            'quantity_kg': d.quantity_kg,
            'food_type': d.food_type,
            'image_url': d.image_url,
            'created_at': d.created_at.strftime('%Y-%m-%d')
        })

    # 4. Return Public Data
    return jsonify({
        'id': target_user.id,
        'organization_name': target_user.organization_name,
        'business_type': target_user.business_type,
        'impact_tier': target_user.impact_tier, # Bronze, Silver, Gold
        'is_verified': target_user.is_verified,
        'member_since': target_user.created_at.strftime('%B %Y') if hasattr(target_user, 'created_at') else "2024", 
        
        # Reputation Stats
        'total_kg_donated': round(total_donated_kg, 1),
        'total_posts': donation_count,
        
        # Engagement
        'active_listings': active_list
    }), 200

@user_bp.route('/api/leaderboard', methods=['GET'])
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

@user_bp.route('/api/certificate/download', methods=['GET'])
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
    
@user_bp.route('/api/report/download', methods=['GET'])
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

@user_bp.route('/api/donor/stats', methods=['GET'])
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

@user_bp.route('/api/recipient/stats', methods=['GET'])
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
    
@user_bp.route('/api/delete-account', methods=['DELETE'])
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
    
@user_bp.route('/api/watchlist', methods=['POST'])
@jwt_required()
def add_watchlist_item():
    """ Rescuer subscribes to a food type (e.g., 'Bakery'). """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    food_type = data.get('food_type')
    if not food_type:
        return jsonify({'error': 'Food type required'}), 400

    # Prevent Duplicates
    exists = Watchlist.query.filter_by(user_id=current_user_id, food_type=food_type).first()
    if exists:
        return jsonify({'message': 'You are already watching this category.'}), 200

    new_item = Watchlist(user_id=current_user_id, food_type=food_type)
    db.session.add(new_item)
    db.session.commit()
    
    return jsonify({'message': f'Alert set! We will email you when {food_type} is posted.'}), 201

@user_bp.route('/api/watchlist/<int:id>', methods=['DELETE'])
@jwt_required()
def remove_watchlist_item(id):
    """ Stop watching. """
    current_user_id = get_jwt_identity()
    item = Watchlist.query.get(id)
    
    if not item or str(item.user_id) != str(current_user_id):
        return jsonify({'error': 'Not found or unauthorized'}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Alert removed.'}), 200

@user_bp.route('/api/watchlist', methods=['GET'])
@jwt_required()
def get_watchlist():
    """ View active alerts. """
    current_user_id = get_jwt_identity()
    items = Watchlist.query.filter_by(user_id=current_user_id).all()
    
    return jsonify([{
        'id': i.id,
        'food_type': i.food_type,
        'created_at': i.created_at.strftime('%Y-%m-%d')
    } for i in items]), 200    
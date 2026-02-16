from flask import Blueprint, app, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token
from sqlalchemy import func, desc
from models import db, User, Donation, Claim
from flask_mail import Message
from extensions import mail
from utils import log_activity

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/api/admin/stats', methods=['GET'])
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

@admin_bp.route('/api/admin/users-list', methods=['GET'])
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

@admin_bp.route('/api/admin/claims-log', methods=['GET'])
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

@admin_bp.route('/api/admin/verify/<int:user_id>', methods=['PATCH', 'POST'])
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

@admin_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
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
    
@admin_bp.route('/api/admin/search', methods=['GET'])
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
    
# routes/admin.py

@admin_bp.route('/api/admin/pending-list', methods=['GET'])
@jwt_required()
def get_pending_details():
    """
    Called when Admin clicks 'Pending' card.
    Shows users waiting for approval + registration date.
    """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if user.role != 'admin': 
        return jsonify({'error': 'Admins only'}), 403

    # Fetch all unverified users
    pending_users = User.query.filter_by(is_verified=False).all()
    results = []

    for u in pending_users:
        results.append({
            'id': u.id,
            'organization_name': u.organization_name,
            'email': u.email,
            'role': u.role,
            'business_type': u.business_type,
            'registration_number': u.registration_number,
            'verification_proof': u.verification_proof, # Essential for Admin vetting
            # Use 'created_at' if it exists, otherwise fallback to today's date logic
            'joined_at': u.created_at.strftime('%Y-%m-%d') if u.created_at else "N/A"
        })

    return jsonify(results), 200   

@admin_bp.route('/api/admin/food-breakdown', methods=['GET'])
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
    
@admin_bp.route('/api/admin/reset-password', methods=['POST'])
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
    
    
# ==========================================
#  GOD MODE: IMPERSONATION (Debugging)
# ==========================================
@admin_bp.route('/api/admin/impersonate/<int:user_id>', methods=['POST'])
@jwt_required()
def impersonate_user(user_id):
    """
    Allows a Super Admin to generate a login token for ANY user.
    Useful for debugging: "I can't see the button!" -> Admin logs in as them to check.
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)

    # 1. Security: Absolute Must
    if admin.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({'error': 'User not found'}), 404

    # 2. Prevent "Super Admin" Impersonation (Safety)
    if target_user.role == 'admin':
        return jsonify({'error': 'Cannot impersonate another Admin.'}), 403

    # 3. Generate Token for the TARGET
    # We add a special flag 'impersonator_id' so the frontend knows this is a fake session
    additional_claims = {
        "role": target_user.role, 
        "org": target_user.organization_name,
        "is_impersonated": True,
        "real_admin_id": admin.id
    }
    access_token = create_access_token(identity=str(target_user.id), additional_claims=additional_claims)

    log_activity(admin.id, "IMPERSONATION", f"Admin logged in as {target_user.email}")

    return jsonify({
        'message': f'Now logged in as {target_user.organization_name}',
        'access_token': access_token,
        'user': {
            'id': target_user.id,
            'email': target_user.email,
            'role': target_user.role,
            'organization_name': target_user.organization_name
        }
    }), 200


# ==========================================
#  GOD MODE: BROADCAST (Emergency)
# ==========================================
@admin_bp.route('/api/admin/broadcast', methods=['POST'])
@jwt_required()
def send_broadcast():
    """
    Sends an email to ALL users (or specific roles).
    Use Case: "Server Maintenance" or "Emergency Flood Alert".
    """
    current_user_id = get_jwt_identity()
    admin = User.query.get(current_user_id)

    if admin.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    subject = data.get('subject')
    message_body = data.get('message')
    target_role = data.get('target_role') # 'all', 'donor', 'rescuer'

    if not subject or not message_body:
        return jsonify({'error': 'Subject and message required'}), 400

    # 1. Select Recipients
    query = User.query
    if target_role and target_role != 'all':
        query = query.filter_by(role=target_role)
    
    # Only verify users get alerts
    recipients = query.filter_by(is_verified=True).all()
    emails = [u.email for u in recipients]

    if not emails:
        return jsonify({'error': 'No recipients found'}), 404

    # 2. Send in Batch (Using BCC to hide emails from each other)
    try:
        msg = Message(
            subject=f"[FRN Alert] {subject}",
            recipients=[app.config['MAIL_USERNAME']], # Send 'To' yourself
            bcc=emails # 'BCC' everyone else for privacy
        )
        msg.body = f"""IMPORTANT MESSAGE FROM FOOD RESCUE NETWORK
        
{message_body}

------------------------------------------------
This is an automated system broadcast.
"""
        mail.send(msg)
        
        log_activity(admin.id, "BROADCAST", f"Sent alert '{subject}' to {len(emails)} users.")
        
        return jsonify({'message': f'Broadcast sent to {len(emails)} users.'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500    
    

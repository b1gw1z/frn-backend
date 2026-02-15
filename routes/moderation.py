from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Report, Donation, User
from utils import log_activity

moderation_bp = Blueprint('moderation', __name__)

@moderation_bp.route('/api/report', methods=['POST'])
@jwt_required()
def report_donation():
    """
    Allows a user to flag a donation.
    ⚡ AUTO-MODERATION: If a donation gets 3 distinct reports, hide it automatically.
    """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    donation_id = data.get('donation_id')
    reason = data.get('reason')

    if not donation_id or not reason:
        return jsonify({'error': 'Missing fields'}), 400

    # 1. Prevent Duplicate Reporting
    existing = Report.query.filter_by(reporter_id=current_user_id, donation_id=donation_id).first()
    if existing:
        return jsonify({'error': 'You have already reported this item.'}), 400

    # 2. Create Report
    new_report = Report(
        reporter_id=current_user_id,
        donation_id=donation_id,
        reason=reason
    )
    
    db.session.add(new_report)
    
    # 3. ⚡ AUTO-MODERATION LOGIC
    # Check how many reports this donation has now
    report_count = Report.query.filter_by(donation_id=donation_id).count()
    
    donation = Donation.query.get(donation_id)
    
    if report_count >= 3: # Threshold
        donation.status = 'under_review' # Auto-hide from feed
        log_activity(current_user_id, "AUTO_MODERATION", f"Donation {donation.id} hidden due to high report volume.")
        msg = "Report submitted. This item has been flagged for urgent review."
    else:
        msg = "Report submitted. Thank you for keeping the community safe."

    db.session.commit()
    return jsonify({'message': msg}), 201

# --- ADMIN ENDPOINT TO VIEW REPORTS ---
@moderation_bp.route('/api/admin/reports', methods=['GET'])
@jwt_required()
def get_reports():
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    reports = Report.query.order_by(Report.timestamp.desc()).all()
    results = []
    
    for r in reports:
        results.append({
            'id': r.id,
            'reason': r.reason,
            'reporter': r.reporter.organization_name,
            'donation_title': r.donation.title,
            'donation_id': r.donation.id,
            'status': r.status,
            'timestamp': r.timestamp.strftime('%Y-%m-%d %H:%M')
        })
        
    return jsonify(results), 200
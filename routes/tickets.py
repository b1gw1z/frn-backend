from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from models import db, Ticket, User, Claim
from utils import log_activity

tickets_bp = Blueprint('tickets', __name__)

# ==========================================
#  1. USER: CREATE A TICKET
# ==========================================
@tickets_bp.route('/api/tickets', methods=['POST'])
@jwt_required()
def create_ticket():
    """
    Allows any user (Donor or Rescuer) to file a complaint.
    """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    if not data.get('subject') or not data.get('description'):
        return jsonify({'error': 'Subject and Description are required.'}), 400

    new_ticket = Ticket(
        reporter_id=current_user_id,
        claim_id=data.get('claim_id'), # Optional: Link to a specific food pickup
        subject=data['subject'],
        description=data['description'],
        priority=data.get('priority', 'medium')
    )
    
    try:
        db.session.add(new_ticket)
        db.session.commit()
        
        # Log it so Admins see it in the audit trail immediately
        log_activity(current_user_id, "CREATE_TICKET", f"Filed ticket: {new_ticket.subject}")
        
        return jsonify({'message': 'Ticket submitted successfully. Support will review it shortly.'}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ==========================================
#  2. USER: VIEW MY TICKETS
# ==========================================
@tickets_bp.route('/api/tickets', methods=['GET'])
@jwt_required()
def get_my_tickets():
    """ Shows the user their own support history. """
    current_user_id = get_jwt_identity()
    
    tickets = Ticket.query.filter_by(reporter_id=current_user_id)\
        .order_by(Ticket.created_at.desc()).all()
        
    results = []
    for t in tickets:
        results.append({
            'id': t.id,
            'subject': t.subject,
            'status': t.status,
            'created_at': t.created_at.strftime('%Y-%m-%d'),
            'admin_response': t.admin_response
        })
        
    return jsonify(results), 200


# ==========================================
#  3. ADMIN: VIEW ALL TICKETS
# ==========================================
@tickets_bp.route('/api/admin/tickets', methods=['GET'])
@jwt_required()
def get_all_tickets():
    """ Admin Inbox for all complaints. """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Filter by status if provided (e.g. ?status=open)
    status_filter = request.args.get('status')
    
    query = Ticket.query
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    tickets = query.order_by(Ticket.created_at.desc()).all()
    
    results = []
    for t in tickets:
        results.append({
            'id': t.id,
            'reporter': t.reporter.organization_name,
            'subject': t.subject,
            'description': t.description,
            'priority': t.priority,
            'status': t.status,
            'created_at': t.created_at.strftime('%Y-%m-%d %H:%M'),
            'claim_id': t.claim_id
        })
        
    return jsonify(results), 200


# ==========================================
#  4. ADMIN: RESOLVE TICKET
# ==========================================
@tickets_bp.route('/api/admin/tickets/<int:ticket_id>/resolve', methods=['POST'])
@jwt_required()
def resolve_ticket(ticket_id):
    """ Admin replies to and closes a ticket. """
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    
    if user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.get_json()
    response_text = data.get('response')
    
    if not response_text:
        return jsonify({'error': 'Response text required'}), 400

    ticket = Ticket.query.get(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket not found'}), 404
        
    ticket.status = 'resolved'
    ticket.admin_response = response_text
    ticket.resolved_at = datetime.utcnow()
    
    db.session.commit()
    
    # Notify user (Logic for notification/email would go here)
    log_activity(current_user_id, "RESOLVE_TICKET", f"Resolved Ticket #{ticket.id}")
    
    return jsonify({'message': 'Ticket resolved and user notified.'}), 200
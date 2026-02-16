from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, and_, desc
from models import db, Message, User, Donation, Contact
from extensions import socketio
from utils import get_avatar_url

messaging_bp = Blueprint('messaging', __name__)

# ==========================================
#  1. SEND MESSAGE
# ==========================================
@messaging_bp.route('/api/messages', methods=['POST'])
@jwt_required()
def send_message():
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    receiver_id = data.get('receiver_id')
    donation_id = data.get('donation_id')
    text = data.get('text')
    
    if not all([receiver_id, donation_id, text]):
        return jsonify({'error': 'Missing required fields'}), 400
        
    if str(receiver_id) == str(current_user_id):
        return jsonify({'error': 'You cannot message yourself.'}), 400

    # Verify Donation Exists
    donation = db.session.get(Donation, donation_id)
    if not donation:
        return jsonify({'error': 'Donation topic not found.'}), 404

    new_msg = Message(
        sender_id=current_user_id,
        receiver_id=receiver_id,
        donation_id=donation_id,
        text=text
    )
    
    try:
        db.session.add(new_msg)
        db.session.commit()
        
        # Real-time Notification
        socketio.emit('new_message', {
            'sender_id': current_user_id,
            'text': text,
            'donation_id': donation_id,
            'timestamp': new_msg.timestamp.strftime('%Y-%m-%d %H:%M')
        }, room=str(receiver_id))
        
        return jsonify({'message': 'Message sent!', 'id': new_msg.id}), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ==========================================
#  2. GET CONVERSATION (Privacy Enforced)
# ==========================================
@messaging_bp.route('/api/messages/<int:partner_id>', methods=['GET'])
@jwt_required()
def get_conversation(partner_id):
    """ Fetches chat history strictly between Me and You about a Donation. """
    current_user_id = get_jwt_identity()
    donation_id = request.args.get('donation_id')
    
    if not donation_id:
        return jsonify({'error': 'donation_id query parameter required'}), 400

    msgs = Message.query.filter(
        Message.donation_id == donation_id,
        or_(
            and_(Message.sender_id == current_user_id, Message.receiver_id == partner_id),
            and_(Message.sender_id == partner_id, Message.receiver_id == current_user_id)
        )
    ).order_by(Message.timestamp.asc()).all()

    # Get Nickname if it exists
    contact_entry = Contact.query.filter_by(owner_id=current_user_id, contact_user_id=partner_id).first()
    partner_user = db.session.get(User, partner_id)
    
    display_name = contact_entry.nickname if (contact_entry and contact_entry.nickname) else partner_user.organization_name

    output = []
    for m in msgs:
        output.append({
            'id': m.id,
            'sender_id': m.sender_id,
            'text': m.text,
            'timestamp': m.timestamp.strftime('%Y-%m-%d %H:%M'),
            'is_me': str(m.sender_id) == str(current_user_id)
        })
        
    return jsonify({
        'partner_name': display_name,
        'messages': output
    }), 200

# ==========================================
#  3. GET INBOX (Smart Sort + Search + Nicknames)
# ==========================================
@messaging_bp.route('/api/messages/inbox', methods=['GET'])
@jwt_required()
def get_inbox():
    """
    Returns unique chats grouped by (Partner + Donation).
    - Sorts by LATEST message time (Newest top).
    - SEARCH: Filters by nickname, real name, or donation title.
    """
    current_user_id = get_jwt_identity()
    search_query = request.args.get('search', '').lower()
    
    # 1. Fetch all messages involving me (descending order)
    all_msgs = Message.query.filter(
        or_(Message.sender_id == current_user_id, Message.receiver_id == current_user_id)
    ).order_by(Message.timestamp.desc()).all()

    # 2. Group unique conversations
    # We use a dict to keep only the LATEST message for each (Partner, Donation) pair
    conversations = {} 
    
    for m in all_msgs:
        partner_id = m.receiver_id if str(m.sender_id) == str(current_user_id) else m.sender_id
        key = (partner_id, m.donation_id)
        
        if key not in conversations:
            conversations[key] = m

    # 3. Build Result List
    results = []
    for (partner_id, donation_id), last_msg in conversations.items():
        partner = db.session.get(User, partner_id)
        donation = db.session.get(Donation, donation_id)
        
        if not partner or not donation: 
            continue

        # --- NICKNAME LOGIC ---
        # Check if I have a saved nickname for this person
        contact_entry = Contact.query.filter_by(owner_id=current_user_id, contact_user_id=partner_id).first()
        
        # Priority: Nickname -> Organization Name -> "Unknown"
        display_name = partner.organization_name
        has_nickname = False
        
        if contact_entry and contact_entry.nickname:
            display_name = contact_entry.nickname
            has_nickname = True

        # --- SEARCH LOGIC ---
        # If search query exists, skip items that don't match
        if search_query:
            # We search against: Nickname, Real Name, and Donation Title
            searchable_text = f"{display_name} {partner.organization_name} {donation.title}".lower()
            if search_query not in searchable_text:
                continue

        results.append({
            'partner_id': partner.id,
            'partner_name': display_name,
            'partner_real_name': partner.organization_name, # Frontend might want to show this in small text
            'has_nickname': has_nickname,
            'partner_avatar': get_avatar_url(partner),
            'donation_id': donation.id,
            'donation_title': donation.title,
            'last_message': last_msg.text,
            'timestamp': last_msg.timestamp, # Keep as object for sorting
            'timestamp_str': last_msg.timestamp.strftime('%Y-%m-%d %H:%M')
        })

    # 4. FINAL SORT: Latest timestamp at the top
    results.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Clean up timestamp object before sending JSON
    for r in results:
        del r['timestamp']

    return jsonify(results), 200

# ==========================================
#  4. SET NICKNAME (Manage Contacts)
# ==========================================
@messaging_bp.route('/api/contacts/nickname', methods=['POST'])
@jwt_required()
def set_nickname():
    """ Allows user to save a nickname for a chat partner. """
    current_user_id = get_jwt_identity()
    data = request.get_json()
    
    contact_user_id = data.get('contact_user_id')
    nickname = data.get('nickname') # Can be empty string to reset
    
    if not contact_user_id:
        return jsonify({'error': 'Contact ID required'}), 400

    # Check if contact exists
    contact_entry = Contact.query.filter_by(owner_id=current_user_id, contact_user_id=contact_user_id).first()
    
    if contact_entry:
        # Update existing
        contact_entry.nickname = nickname
    else:
        # Create new
        new_contact = Contact(owner_id=current_user_id, contact_user_id=contact_user_id, nickname=nickname)
        db.session.add(new_contact)

    try:
        db.session.commit()
        return jsonify({'message': 'Nickname saved successfully!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
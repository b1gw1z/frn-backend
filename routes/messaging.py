from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, Message

messaging_bp = Blueprint('messaging', __name__)

@messaging_bp.route('/api/messages', methods=['POST'])
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

@messaging_bp.route('/api/messages/<int:donation_id>', methods=['GET'])
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
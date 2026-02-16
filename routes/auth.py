from flask import Blueprint, request, jsonify, url_for
from flask_jwt_extended import create_access_token
from werkzeug.security import check_password_hash
from datetime import timedelta
from models import db, User
from utils import send_verification_email, get_avatar_url
from flask_mail import Message
from extensions import mail # Import mail from main app
from unittest.mock import patch

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/api/register', methods=['POST'])
def register_business():
    data = request.get_json()

    # 1.1 Strict B2B Validation
    required_fields = ['email', 'password', 'role', 'latitude', 'longitude', 
                       'organization_name', 'registration_number', 'business_type']
    
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    # --- NEW: STRICT VALIDATION FOR RESCUERS (NGOs) ---
    if data['role'] == 'rescuer':
        # 1. Must have a document uploaded
        if not data.get('verification_proof'):
            return jsonify({'error': 'NGOs must provide a verification document (CAC/Permit).'}), 400
        
        # 2. Must be a valid Org Type
        valid_types = ['NGO', 'Orphanage', 'Shelter', 'Food Bank', 'Religious Group', 'Community Center']
        if data['business_type'] not in valid_types:
            return jsonify({'error': f'Invalid Organization Type for Rescuers. Must be one of: {", ".join(valid_types)}'}), 400
    # --------------------------------------------------

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

@auth_bp.route('/api/auth/register-individual', methods=['POST'])
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
    
@auth_bp.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()

    # 1. Validate Input
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing email or password'}), 400

    user = User.query.filter_by(email=data['email']).first()

    # 2. Check Password 
    # (Uses the model method for cleaner code)
    if user and user.check_password(data['password']):
        
        # Add Role & Org Name to Token Claims
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
                'impact_tier': user.impact_tier,
                
                # --- NEW UPDATES ---
                'phone': user.phone,  # <--- Added Phone
                'profile_picture': get_avatar_url(user) # <--- Uses Smart Initials Fallback
            }
        }), 200
    else:
        return jsonify({'error': 'Invalid email or password'}), 401
@auth_bp.route('/api/forgot-password', methods=['POST'])
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

@auth_bp.route('/api/auth/verify-email/<token>', methods=['GET'])
def verify_email(token):
    user = User.verify_token(token)
    
    if not user:
        return jsonify({'error': 'Invalid or expired token.'}), 400
        
    if user.is_verified:
        return jsonify({'message': 'Account already verified.'}), 200

    user.is_verified = True
    db.session.commit()
    
    return jsonify({'message': 'Email verified! You can now log in.'}), 200

# ==========================================
#  3. PASSWORD RESET FLOW (Comprehensive)
# ==========================================
def test_password_reset_request_success(client):
    """ 
    Should return 200 and pretend to send email.
    We MOCK the mail.send function so we don't need a real mail server.
    """
    # 1. Create User
    client.post('/api/register', json={
        "email": "reset_me@example.com", "password": "oldpassword", "role": "donor",
        "organization_name": "Reset Co", "registration_number": "CAC-RESET",
        "business_type": "Tech", "latitude": 0, "longitude": 0
    })

    # 2. Mock the Mail sender to avoid 500 Errors
    with patch('extensions.mail.send') as mock_mail:
        response = client.post('/api/reset-password-request', json={"email": "reset_me@example.com"})
        
        # 3. Assert Success
        assert response.status_code == 200
        assert b"reset link has been sent" in response.data or b"successful" in response.data
        
        # 4. Verify that the app TRIED to send an email
        assert mock_mail.called

def test_password_reset_unknown_email(client):
    """ Should handle unknown emails gracefully (Security: Don't reveal user existence) """
    # Depending on your security setting, this might return 200 (to hide user existence) or 404.
    # Standard practice is often 200 with a generic message, or 404 if less strict.
    # Adjust assertion based on your specific route logic.
    with patch('extensions.mail.send'):
        response = client.post('/api/reset-password-request', json={"email": "ghost@example.com"})
        assert response.status_code != 500 # Ensure it doesn't crash

# ==========================================
#  4. EMAIL VERIFICATION FLOW (Comprehensive)
# ==========================================
def test_verify_email_success(client):
    """ 
    Should successfully verify a user when given a valid token.
    """
    # 1. Create a User (Initially Unverified)
    email = "verify_me@example.com"
    client.post('/api/register', json={
        "email": email, "password": "password", "role": "donor",
        "organization_name": "Verify Co", "registration_number": "CAC-VERIFY",
        "business_type": "Tech", "latitude": 0, "longitude": 0
    })
    
    # 2. Get the User from DB to generate a REAL token
    # (We bypass the email and generate the token directly using the Model)
    user = User.query.filter_by(email=email).first()
    assert user.is_verified is False # Confirm start state
    
    # Generate valid token using the method in your User model
    valid_token = user.get_verification_token()

    # 3. Call the Verify Endpoint with the VALID token
    response = client.get(f'/api/verify-email/{valid_token}')
    
    # 4. Assert Success
    assert response.status_code == 200
    assert b"Email verified" in response.data

    # 5. DB Check: Ensure the user is actually verified now
    db.session.refresh(user) # Refresh data from DB
    assert user.is_verified is True

def test_verify_email_invalid_token(client):
    """ Should fail with invalid token """
    response = client.get('/api/verify-email/INVALID_TOKEN_123')
    assert response.status_code == 400
    assert b"Invalid or expired" in response.data

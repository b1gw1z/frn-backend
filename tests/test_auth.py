import pytest
import json
from unittest.mock import patch
from models import User
from extensions import db
from geoalchemy2.elements import WKTElement 

# ==========================================
#  1. BUSINESS REGISTRATION TESTS
# ==========================================

def test_register_business_success(client):
    """Happy Path: Standard Business Registration."""
    User.query.filter_by(email="biz@test.com").delete()
    db.session.commit()

    payload = {
        "email": "biz@test.com",
        "password": "password",
        "role": "donor",
        "organization_name": "Test Biz",
        "registration_number": "CAC-BIZ-001",
        "business_type": "Restaurant",
        "latitude": 6.5,
        "longitude": 3.3
    }
    response = client.post('/api/register', json=payload)
    
    assert response.status_code == 201
    assert "successful" in response.get_json()['message']
    
    # DB Check
    user = User.query.filter_by(email="biz@test.com").first()
    assert user is not None
    assert user.role == "donor"

def test_register_ngo_missing_docs(client):
    """Edge Case: NGO (Rescuer) must provide verification_proof."""
    payload = {
        "email": "ngo@test.com",
        "password": "password",
        "role": "rescuer", 
        "organization_name": "Test NGO",
        "registration_number": "CAC-NGO-001",
        "business_type": "NGO",
        "latitude": 6.5, "longitude": 3.3
        # MISSING: verification_proof
    }
    response = client.post('/api/register', json=payload)
    
    assert response.status_code == 400
    assert "must provide a verification document" in response.get_json()['error']

def test_register_duplicate_cac(client):
    """Edge Case: Cannot reuse CAC number."""
    # 1. Create first user
    User.query.filter_by(registration_number="CAC-DUP").delete()
    user = User(
        email="u1@test.com", username="u1", role="donor",
        organization_name="U1", registration_number="CAC-DUP",
        business_type="Biz", is_verified=True
    )
    user.set_password("pass")
    db.session.add(user)
    db.session.commit()

    # 2. Try to register second user with same CAC
    payload = {
        "email": "u2@test.com", "password": "pass", "role": "donor",
        "organization_name": "U2", "registration_number": "CAC-DUP",
        "business_type": "Biz", "latitude": 0, "longitude": 0
    }
    response = client.post('/api/register', json=payload)
    
    assert response.status_code == 400
    assert "already exists" in response.get_json()['error']

# ==========================================
#  2. INDIVIDUAL REGISTRATION TESTS
# ==========================================

def test_register_individual_success(client):
    """Happy Path: Individual Registration."""
    User.query.filter_by(email="indiv@test.com").delete()
    db.session.commit()

    payload = {
        "email": "indiv@test.com",
        "password": "password",
        "full_name": "John Doe",
        "phone": "08012345678",
        "location": "POINT(3.3 6.5)" 
    }
    
    # Mock email sending so test doesn't crash
    with patch('extensions.mail.send'):
        response = client.post('/api/auth/register-individual', json=payload)

    assert response.status_code == 201
    
    # DB Check
    user = User.query.filter_by(email="indiv@test.com").first()
    assert user is not None
    assert user.organization_name == "John Doe"
    assert user.role == "individual"

# ==========================================
#  3. LOGIN TESTS
# ==========================================

def test_login_success(client):
    """Happy Path: Login returns token and user data."""
    User.query.filter_by(email="login@test.com").delete()
    user = User(
        email="login@test.com", username="LoginUser", role="donor",
        organization_name="Login Corp", registration_number="CAC-LOG",
        business_type="Biz", is_verified=True
    )
    user.set_password("password")
    db.session.add(user)
    db.session.commit()

    response = client.post('/api/login', json={
        "email": "login@test.com",
        "password": "password"
    })

    assert response.status_code == 200
    data = response.get_json()
    assert "access_token" in data
    assert data['user']['email'] == "login@test.com"

def test_login_fail_wrong_password(client):
    """Edge Case: Wrong password."""
    User.query.filter_by(email="wrong@test.com").delete()
    user = User(
        email="wrong@test.com", username="Wrong", role="donor",
        organization_name="Wrong", registration_number="CAC-WRONG",
        business_type="Biz"
    )
    user.set_password("correct")
    db.session.add(user)
    db.session.commit()

    response = client.post('/api/login', json={
        "email": "wrong@test.com",
        "password": "WRONG"
    })
    
    assert response.status_code == 401

# ==========================================
#  4. PASSWORD RESET TESTS
# ==========================================

def test_forgot_password_email_sent(client):
    """Ensure endpoint calls mail.send when email exists."""
    # Setup
    User.query.filter_by(email="reset@test.com").delete()
    user = User(
        email="reset@test.com", username="Reset", role="donor",
        organization_name="Reset", registration_number="CAC-RES",
        business_type="Biz"
    )
    # FIX: Must set password hash to avoid IntegrityError
    user.set_password("old_password") 
    db.session.add(user)
    db.session.commit()

    with patch('extensions.mail.send') as mock_send:
        response = client.post('/api/forgot-password', json={
            "email": "reset@test.com"
        })
        
        assert response.status_code == 200
        assert "sent" in response.get_json()['message']
        assert mock_send.called

def test_forgot_password_unknown_email(client):
    """Ensure it doesn't crash on unknown email."""
    with patch('extensions.mail.send') as mock_send:
        response = client.post('/api/forgot-password', json={
            "email": "ghost@test.com"
        })
        assert response.status_code == 200 
        assert not mock_send.called

# ==========================================
#  5. EMAIL VERIFICATION TESTS
# ==========================================

def test_verify_email_success(client):
    """End-to-End verification flow."""
    # 1. Setup Unverified User
    User.query.filter_by(email="verify@test.com").delete()
    user = User(
        email="verify@test.com", username="Verify", role="donor",
        organization_name="Verify", registration_number="CAC-VER",
        business_type="Biz", is_verified=False
    )
    # FIX: Must set password hash to avoid IntegrityError
    user.set_password("password") 
    db.session.add(user)
    db.session.commit()

    # 2. Generate Real Token
    token = user.get_verification_token()

    # 3. Call Endpoint
    response = client.get(f'/api/auth/verify-email/{token}')
    
    assert response.status_code == 200
    assert "Email verified" in response.get_json()['message']

    # 4. Verify DB Update
    db.session.refresh(user)
    assert user.is_verified is True
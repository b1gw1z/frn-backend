import json
import pytest

# ==========================================
#  REGISTRATION TESTS
# ==========================================

def test_register_donor_success(client):
    """ Should create a new user and return 201 """
    payload = {
        "email": "test_donor@example.com",
        "password": "securepassword",
        "role": "donor",
        "organization_name": "Test Hotel",
        "registration_number": "CAC-11111",
        "business_type": "Hospitality",
        "latitude": 6.5244,
        "longitude": 3.3792
    }
    response = client.post('/api/register', json=payload)
    assert response.status_code == 201
    assert b"Registration successful" in response.data

def test_register_duplicate_fail(client):
    """ Should return 400 if email already exists """
    # 1. Register User A
    payload = {
        "email": "duplicate@example.com",
        "password": "password",
        "role": "donor",
        "organization_name": "Org A",
        "registration_number": "CAC-22222",
        "business_type": "NGO",
        "latitude": 0, "longitude": 0
    }
    client.post('/api/register', json=payload)

    # 2. Try to Register User A AGAIN
    response = client.post('/api/register', json=payload)
    
    # 3. Expect Failure
    assert response.status_code == 400
    assert b"already exists" in response.data

def test_register_missing_fields(client):
    """ Should return 400 if fields are missing """
    payload = {
        "email": "incomplete@example.com",
        # Missing password, role, etc.
    }
    response = client.post('/api/register', json=payload)
    assert response.status_code == 400
    assert b"Missing required field" in response.data

# ==========================================
#  LOGIN TESTS
# ==========================================

def test_login_success(client):
    """ Should return 200, Token, AND User Role """
    # 1. Create User
    client.post('/api/register', json={
        "email": "login_user@example.com",
        "password": "mypassword",
        "role": "donor",
        "organization_name": "Login Corp",
        "registration_number": "CAC-33333",
        "business_type": "Retail",
        "latitude": 0, "longitude": 0
    })

    # 2. Login
    login_payload = {
        "email": "login_user@example.com",
        "password": "mypassword"
    }
    response = client.post('/api/login', json=login_payload)

    # 3. Check Result
    assert response.status_code == 200
    data = json.loads(response.data)
    
    # Professional Check: Ensure all critical keys exist
    assert "access_token" in data
    assert "user" in data  # <--- We now check for the 'user' object
    assert data["user"]["role"] == "donor" # <--- Checking inside the object
    assert data["user"]["email"] == "login_user@example.com"

def test_login_wrong_password(client):
    """ Should return 401 for bad password """
    # 1. Create User
    client.post('/api/register', json={
        "email": "wrong_pass@example.com",
        "password": "correct_password",
        "role": "donor",
        "organization_name": "Wrong Corp",
        "registration_number": "CAC-44444",
        "business_type": "Retail",
        "latitude": 0, "longitude": 0
    })

    # 2. Login with WRONG password
    response = client.post('/api/login', json={
        "email": "wrong_pass@example.com",
        "password": "WRONG_PASSWORD"
    })

    assert response.status_code == 401
    assert b"Invalid email or password" in response.data

def test_login_non_existent_user(client):
    """ Should return 401 if email doesn't exist """
    response = client.post('/api/login', json={
        "email": "ghost@example.com",
        "password": "password"
    })
    assert response.status_code == 401
    assert b"Invalid email or password" in response.data
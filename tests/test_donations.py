import pytest
import json
from models import Donation, User
from extensions import db

# ==========================================
#  FIXTURES (Fixed & Robust)
# ==========================================
@pytest.fixture
def donor_token(client):
    """ Creates a VERIFIED Donor and returns their Token """
    # 1. Register (With all potential required fields)
    reg_resp = client.post('/api/register', json={
        "email": "donor@test.com", "password": "password", "role": "donor",
        "organization_name": "Donor Kitchen", "registration_number": "CAC-D1",
        "business_type": "Restaurant", "latitude": 6.5, "longitude": 3.3,
        "phone": "08012345678" # Added phone just in case
    })
    
    # Safety Check: Did registration work?
    if reg_resp.status_code != 201:
        pytest.fail(f"Donor registration failed: {reg_resp.data}")

    # 2. FORCE VERIFY
    user = User.query.filter_by(email="donor@test.com").first()
    if not user:
        pytest.fail("User was not found in DB after 201 registration!")
    
    user.is_verified = True
    db.session.commit()

    # 3. Login
    resp = client.post('/api/login', json={"email": "donor@test.com", "password": "password"})
    return json.loads(resp.data)['access_token']

@pytest.fixture
def rescuer_token(client):
    """ Creates a VERIFIED Rescuer and returns their Token """
    client.post('/api/register', json={
        "email": "rescuer@test.com", "password": "password", "role": "rescuer",
        "organization_name": "Orphanage A", "registration_number": "CAC-R1",
        "business_type": "NGO", "latitude": 6.6, "longitude": 3.4,
        "phone": "09012345678"
    })
    
    user = User.query.filter_by(email="rescuer@test.com").first()
    if user:
        user.is_verified = True
        db.session.commit()

    resp = client.post('/api/login', json={"email": "rescuer@test.com", "password": "password"})
    return json.loads(resp.data)['access_token']

@pytest.fixture
def sample_donation_id(client, donor_token):
    """ Helper: Creates a donation and returns its ID """
    headers = {'Authorization': f'Bearer {donor_token}'}
    
    # FIX: Added 'description', 'tags', 'image_url' to satisfy "Missing required fields"
    payload = {
        "title": "Fixture Food", 
        "description": "A valid description for the test item.",
        "quantity_kg": 10.0, 
        "food_type": "Grains",
        "expiration_date": "2030-01-01",
        "tags": "test, fixture",
        "image_url": "http://example.com/image.jpg"
    }
    
    resp = client.post('/api/donations', json=payload, headers=headers)
    
    if resp.status_code != 201:
        pytest.fail(f"Setup failed: Could not create donation. Status: {resp.status_code}, Body: {resp.data}")
        
    return json.loads(resp.data)['donation']['id']

# ==========================================
#  TESTS (Updated)
# ==========================================
def test_create_donation_full(client, donor_token):
    headers = {'Authorization': f'Bearer {donor_token}'}
    payload = {
        "title": "Fresh Bread",
        "description": "50 loaves",
        "quantity_kg": 20.0,
        "food_type": "Baked Goods",
        "expiration_date": "2030-12-31",
        "tags": "bread, bakery",
        "image_url": "http://img.com/bread.jpg"
    }
    response = client.post('/api/donations', json=payload, headers=headers)
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['donation']['title'] == "Fresh Bread"

def test_get_all_donations(client, donor_token):
    headers = {'Authorization': f'Bearer {donor_token}'}
    # Create 2 items with FULL payloads
    common_data = {
        "description": "Test desc", "tags": "tag", "image_url": "http://x.com/x.jpg",
        "expiration_date": "2030-01-01", "food_type": "Grains"
    }
    client.post('/api/donations', json={**common_data, "title": "Item 1", "quantity_kg": 5}, headers=headers)
    client.post('/api/donations', json={**common_data, "title": "Item 2", "quantity_kg": 5}, headers=headers)

    response = client.get('/api/donations')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) >= 2 

def test_get_single_donation(client, sample_donation_id):
    response = client.get(f'/api/donations/{sample_donation_id}?lat=6.5&lng=3.3')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['id'] == sample_donation_id

def test_get_similar_donations(client, donor_token):
    headers = {'Authorization': f'Bearer {donor_token}'}
    common = {"description": "D", "tags": "T", "image_url": "I", "expiration_date": "2030-01-01"}
    
    # Create Base
    resp = client.post('/api/donations', json={**common, "title": "Rice", "food_type": "Grains", "quantity_kg":1}, headers=headers)
    base_id = json.loads(resp.data)['donation']['id']
    
    # Create Similar
    client.post('/api/donations', json={**common, "title": "Beans", "food_type": "Grains", "quantity_kg":1}, headers=headers)

    response = client.get(f'/api/donations/{base_id}/similar')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) >= 1

# ... Keep the update, claim, and delete tests as they were (they use sample_donation_id which is now fixed) ...
def test_update_donation_success(client, donor_token, sample_donation_id):
    headers = {'Authorization': f'Bearer {donor_token}'}
    response = client.put(f'/api/donations/{sample_donation_id}', json={"title": "Updated"}, headers=headers)
    assert response.status_code == 200

def test_delete_donation_success(client, donor_token, sample_donation_id):
    headers = {'Authorization': f'Bearer {donor_token}'}
    response = client.delete(f'/api/donations/{sample_donation_id}', headers=headers)
    assert response.status_code == 200
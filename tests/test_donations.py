import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import patch
from geoalchemy2.elements import WKTElement
from models import Donation, User, Claim
from extensions import db

# ==========================================
#  ROBUST FIXTURES
# ==========================================

@pytest.fixture
def clean_db():
    """Cleanup database before each test to ensure isolation."""
    db.session.query(Claim).delete()
    db.session.query(Donation).delete()
    db.session.query(User).delete()
    db.session.commit()

@pytest.fixture
def donor_user(client, clean_db):
    """Verified Donor User."""
    user = User(
        username="donor_king",
        email="donor@test.com",
        role="donor",
        organization_name="Pro Kitchen",
        registration_number="CAC-DONOR",
        business_type="Restaurant",
        location=WKTElement('POINT(3.0 6.0)', srid=4326), # Lagos
        is_verified=True,
        points=0
    )
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def unverified_donor(client, clean_db):
    """Unverified Donor (Should be blocked)."""
    user = User(
        username="newbie",
        email="new@test.com",
        role="donor",
        organization_name="New Biz",
        registration_number="CAC-NEW",
        business_type="Restaurant",
        is_verified=False 
    )
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def rescuer_user(client, clean_db):
    """Verified Rescuer (NGO)."""
    user = User(
        username="rescuer_hero",
        email="rescuer@test.com",
        role="rescuer",
        organization_name="Save Lives NGO",
        registration_number="CAC-NGO",
        business_type="NGO",
        location=WKTElement('POINT(3.1 6.1)', srid=4326), # Nearby
        is_verified=True
    )
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def donor_headers(client, donor_user):
    resp = client.post('/api/login', json={"email": donor_user.email, "password": "password"})
    return {'Authorization': f'Bearer {resp.get_json()["access_token"]}'}

@pytest.fixture
def rescuer_headers(client, rescuer_user):
    resp = client.post('/api/login', json={"email": rescuer_user.email, "password": "password"})
    return {'Authorization': f'Bearer {resp.get_json()["access_token"]}'}

@pytest.fixture
def donation_factory(donor_user):
    def _create(**kwargs):
        defaults = {
            "title": "Jollof Rice",
            "description": "Hot and fresh",
            "quantity_kg": 10.0,
            "initial_quantity_kg": 10.0,
            "food_type": "Cooked Meals",
            "expiration_date": datetime.utcnow() + timedelta(days=2),
            "donor_id": donor_user.id,
            "status": "available"
        }
        defaults.update(kwargs)
        item = Donation(**defaults)
        db.session.add(item)
        db.session.commit()
        return item
    return _create

# ==========================================
#  1. CREATE DONATION TESTS (POST)
# ==========================================

def test_create_donation_success(client, donor_headers):
    """Happy Path: Verified donor creates item."""
    payload = {
        "title": "Fresh Bread",
        "description": "50 loaves",
        "quantity_kg": 20.0,
        "food_type": "Baked Goods",
        "expiration_date": (datetime.utcnow() + timedelta(days=5)).isoformat()
    }
    response = client.post('/api/donations', json=payload, headers=donor_headers)
    assert response.status_code == 201
    assert Donation.query.count() == 1

def test_create_donation_unverified_blocked(client, unverified_donor):
    """Security: Unverified users cannot post."""
    # Login as unverified
    resp = client.post('/api/login', json={"email": unverified_donor.email, "password": "password"})
    token = resp.get_json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    response = client.post('/api/donations', json={"title": "Test"}, headers=headers)
    assert response.status_code == 403
    assert "not verified" in response.get_json()['error']

def test_create_donation_invalid_date(client, donor_headers):
    """Edge Case: Bad date format."""
    response = client.post('/api/donations', json={
        "title": "Test", "quantity_kg": 5, "food_type": "Raw",
        "expiration_date": "not-a-date"
    }, headers=donor_headers)
    assert response.status_code == 400

# ==========================================
#  2. GET DONATIONS & FEED TESTS
# ==========================================

def test_get_donations_filters_expired(client, donor_headers, donation_factory):
    """Logic: Expired items should NOT appear in feed."""
    # 1. Create Valid Item
    valid = donation_factory(title="Valid Item")
    # 2. Create Expired Item (Yesterday)
    expired = donation_factory(title="Expired Item", expiration_date=datetime.utcnow() - timedelta(days=1))
    
    response = client.get('/api/donations', headers=donor_headers)
    data = response.get_json()['donations']
    
    titles = [d['title'] for d in data]
    assert "Valid Item" in titles
    assert "Expired Item" not in titles

def test_get_donations_with_location(client, donor_headers, donation_factory):
    """Logic: Providing lat/lng should calculate distance."""
    donation_factory(title="Lagos Item") # Created by donor at 3.0, 6.0
    
    # Request from nearby (3.1, 6.1)
    response = client.get('/api/donations?lat=6.1&lng=3.1', headers=donor_headers)
    data = response.get_json()['donations'][0]
    
    # We expect 'distance_km' to be a number, not None
    assert data['distance_km'] is not None
    assert data['distance_km'] > 0

# ==========================================
#  3. CLAIMING TESTS (Crucial!)
# ==========================================

def test_claim_donation_success(client, rescuer_headers, donation_factory):
    """Happy Path: Rescuer claims food, points awarded to Donor."""
    donation = donation_factory(quantity_kg=10.0)
    
    # Mock Email to prevent errors
    with patch('extensions.mail.send'):
        response = client.post('/api/claim', json={
            "donation_id": donation.id,
            "quantity_kg": 5.0 # Partial claim
        }, headers=rescuer_headers)

    assert response.status_code == 201
    data = response.get_json()
    assert "pickup_code" in data
    
    # DB Checks
    db.session.expire_all()
    # 1. Check Donation Quantity reduced
    updated_donation = db.session.get(Donation, donation.id)
    assert updated_donation.quantity_kg == 5.0
    assert updated_donation.status == 'partially_claimed'
    
    # 2. Check Donor Points (10kg * 10 points/kg logic usually, but here 5kg claimed)
    donor = db.session.get(User, donation.donor_id)
    assert donor.points == 50 # 5.0kg * 10 points

def test_claim_full_quantity_closes_item(client, rescuer_headers, donation_factory):
    """Logic: Claiming all quantity marks item as 'claimed'."""
    donation = donation_factory(quantity_kg=10.0)
    
    with patch('extensions.mail.send'):
        client.post('/api/claim', json={
            "donation_id": donation.id,
            "quantity_kg": 10.0
        }, headers=rescuer_headers)

    updated_donation = db.session.get(Donation, donation.id)
    assert updated_donation.status == 'claimed'
    assert updated_donation.quantity_kg == 0

def test_claim_fails_if_expired(client, rescuer_headers, donation_factory):
    """Sad Path: Cannot claim expired food."""
    donation = donation_factory(expiration_date=datetime.utcnow() - timedelta(days=1))
    
    response = client.post('/api/claim', json={"donation_id": donation.id}, headers=rescuer_headers)
    assert response.status_code == 400
    assert "expired" in response.get_json()['error']

def test_claim_fails_if_donor_tries(client, donor_headers, donation_factory):
    """Security: Donors cannot claim (only Rescuers)."""
    donation = donation_factory()
    
    response = client.post('/api/claim', json={"donation_id": donation.id}, headers=donor_headers)
    assert response.status_code == 403 # Forbidden

def test_claim_fails_excess_quantity(client, rescuer_headers, donation_factory):
    """Sad Path: Cannot claim more than available."""
    donation = donation_factory(quantity_kg=10.0)
    
    response = client.post('/api/claim', json={
        "donation_id": donation.id,
        "quantity_kg": 50.0 # Too much
    }, headers=rescuer_headers)
    
    assert response.status_code == 400
    assert "Only 10.0kg is available" in response.get_json()['error']

# ==========================================
#  4. UPDATE/DELETE TESTS
# ==========================================

def test_update_donation_success(client, donor_headers, donation_factory):
    donation = donation_factory(title="Old Title")
    response = client.put(f'/api/donations/{donation.id}', json={"title": "New Title"}, headers=donor_headers)
    assert response.status_code == 200
    assert db.session.get(Donation, donation.id).title == "New Title"

def test_delete_donation_forbidden_if_claimed(client, donor_headers, rescuer_headers, donation_factory):
    """Logic: Cannot delete item if someone already claimed it."""
    donation = donation_factory()
    
    # 1. Rescuer claims it fully
    with patch('extensions.mail.send'):
        client.post('/api/claim', json={"donation_id": donation.id, "quantity_kg": 10}, headers=rescuer_headers)
    
    # 2. Donor tries to delete
    response = client.delete(f'/api/donations/{donation.id}', headers=donor_headers)
    assert response.status_code == 400
    assert "already been claimed" in response.get_json()['error']
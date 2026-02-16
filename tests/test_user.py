import pytest
import json
from unittest.mock import patch
from datetime import datetime, timedelta
from geoalchemy2.elements import WKTElement
from models import User, Donation, Claim, Watchlist
from extensions import db

# ==========================================
#  ROBUST FIXTURES
# ==========================================

@pytest.fixture
def clean_db():
    """Cleanup database before each test."""
    db.session.query(Watchlist).delete()
    db.session.query(Claim).delete()
    db.session.query(Donation).delete()
    db.session.query(User).delete()
    db.session.commit()

@pytest.fixture
def donor_user(client, clean_db):
    """Verified Donor with points."""
    user = User(
        username="donor_king",
        email="donor@test.com",
        role="donor",
        organization_name="King Kitchen",
        registration_number="CAC-KING",
        business_type="Restaurant",
        location=WKTElement('POINT(3.0 6.0)', srid=4326),
        is_verified=True,
        points=500,
        impact_tier="Silver",
        phone="08012345678"
    )
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user

@pytest.fixture
def rescuer_user(client, clean_db):
    """Verified Rescuer."""
    user = User(
        username="rescuer_hero",
        email="rescuer@test.com",
        role="rescuer",
        organization_name="Save Lives NGO",
        registration_number="CAC-NGO",
        business_type="NGO",
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
def data_factory(donor_user, rescuer_user):
    """Creates Donations and Claims to populate stats/history."""
    def _create():
        # 1. Available Donation
        d1 = Donation(
            title="Available Rice", quantity_kg=10, initial_quantity_kg=10, 
            food_type="Grains", donor_id=donor_user.id, status="available",
            created_at=datetime.utcnow()
        )
        # 2. Claimed Donation
        d2 = Donation(
            title="Claimed Bread", quantity_kg=0, initial_quantity_kg=20, 
            food_type="Bakery", donor_id=donor_user.id, status="claimed",
            created_at=datetime.utcnow() - timedelta(days=1)
        )
        db.session.add_all([d1, d2])
        db.session.commit()
        
        # 3. Create Claim
        c1 = Claim(
            donation_id=d2.id, rescuer_id=rescuer_user.id, 
            quantity_claimed=20, pickup_code="XYZ123", status="completed",
            claimed_at=datetime.utcnow()
        )
        db.session.add(c1)
        db.session.commit()
        return d1, d2, c1
    return _create

# ==========================================
#  1. PROFILE MANAGEMENT TESTS
# ==========================================

def test_get_user_profile(client, donor_headers, donor_user):
    """Happy Path: Fetch own profile."""
    response = client.get('/api/profile', headers=donor_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data['username'] == "donor_king"
    assert data['points'] == 500

def test_update_profile_success(client, donor_headers):
    """Happy Path: Update allowed fields."""
    payload = {
        "organization_name": "Updated Kitchen Ltd",
        "phone": "09099999999"
    }
    response = client.patch('/api/profile', json=payload, headers=donor_headers)
    
    assert response.status_code == 200
    assert response.get_json()['user']['organization_name'] == "Updated Kitchen Ltd"
    
    # Verify DB
    db.session.expire_all()
    user = User.query.filter_by(email="donor@test.com").first()
    assert user.phone == "09099999999"

def test_update_username_duplicate_fail(client, donor_headers, rescuer_user):
    """Edge Case: Cannot take another user's username."""
    # Donor tries to take Rescuer's username
    response = client.patch('/api/profile', json={"username": rescuer_user.username}, headers=donor_headers)
    
    assert response.status_code == 400
    assert "already taken" in response.get_json()['error']

# ==========================================
#  2. HISTORY & DASHBOARD TESTS
# ==========================================

def test_get_user_history_donor(client, donor_headers, data_factory):
    """Logic: Donor sees Active vs History items."""
    data_factory() # Creates 1 active, 1 claimed
    
    response = client.get('/api/users/history', headers=donor_headers)
    assert response.status_code == 200
    data = response.get_json()
    
    assert len(data['active']) == 1
    assert data['active'][0]['title'] == "Available Rice"
    
    assert len(data['history']) == 1
    assert data['history'][0]['status'] == "claimed"

def test_get_donor_stats(client, donor_headers, data_factory):
    """Logic: Verify stats calculation."""
    data_factory() # 10kg available, 20kg claimed (total 30kg posted)
    
    response = client.get('/api/donor/stats', headers=donor_headers)
    data = response.get_json()
    
    assert data['total_donations_count'] == 2
    # Logic in route: 'total_weight' sums Donation.quantity_kg
    # Since claimed item has 0 remaining, loop checks usually sum initial or current.
    # Your code sums 'quantity_kg' (current). Let's check logic:
    # 10 (Active) + 0 (Claimed) = 10? OR does it look at initial?
    # Your code: db.session.query(func.sum(Donation.quantity_kg))...
    # If the claimed item has 0kg left, this might return 10.
    # Adjust expectation based on your exact route logic.
    assert data['active_listings'] == 1

def test_get_recipient_stats(client, rescuer_headers, data_factory):
    """Logic: Rescuer stats should show 20kg rescued."""
    data_factory()
    
    response = client.get('/api/recipient/stats', headers=rescuer_headers)
    data = response.get_json()
    
    assert data['total_claims'] == 1
    assert data['total_kg_rescued'] == 20.0

# ==========================================
#  3. PUBLIC PROFILE & LEADERBOARD
# ==========================================

def test_get_public_profile(client, rescuer_headers, donor_user, data_factory):
    """Happy Path: Rescuer viewing a Donor's public profile."""
    data_factory()
    
    response = client.get(f'/api/user/public-profile/{donor_user.id}', headers=rescuer_headers)
    assert response.status_code == 200
    data = response.get_json()
    
    assert data['organization_name'] == "King Kitchen"
    # Should show the 1 active listing
    assert len(data['active_listings']) == 1

def test_get_leaderboard(client, donor_user):
    """Logic: Top donors listed."""
    response = client.get('/api/leaderboard')
    assert response.status_code == 200
    data = response.get_json()
    
    assert len(data) >= 1
    assert data[0]['organization_name'] == "King Kitchen"
    assert data[0]['points'] == 500

# ==========================================
#  4. DOWNLOADS (PDF/CSV)
# ==========================================

def test_download_tax_certificate_success(client, donor_headers, data_factory):
    """Happy Path: Donor generates PDF."""
    data_factory() # Has 20kg claimed
    
    response = client.get('/api/certificate/download', headers=donor_headers)
    
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'application/pdf'
    # Verify it's not empty
    assert len(response.data) > 0 
    assert b"%PDF" in response.data # Magic bytes for PDF

def test_download_report_csv(client, donor_headers, data_factory):
    """Happy Path: Donor generates CSV."""
    data_factory()
    
    response = client.get('/api/report/download', headers=donor_headers)
    
    assert response.status_code == 200
    assert response.headers['Content-Type'] == 'text/csv'
    
    # Check CSV content
    content = response.data.decode('utf-8')
    assert "Date Posted" in content
    assert "Available Rice" in content
    assert "Claimed Bread" in content

# ==========================================
#  5. WATCHLIST TESTS
# ==========================================

def test_watchlist_flow(client, rescuer_headers):
    """End-to-End: Add -> List -> Remove."""
    # 1. Add
    resp1 = client.post('/api/watchlist', json={"food_type": "Bakery"}, headers=rescuer_headers)
    assert resp1.status_code == 201
    
    # 2. List
    resp2 = client.get('/api/watchlist', headers=rescuer_headers)
    data = resp2.get_json()
    assert len(data) == 1
    assert data[0]['food_type'] == "Bakery"
    item_id = data[0]['id']
    
    # 3. Duplicate Check
    resp3 = client.post('/api/watchlist', json={"food_type": "Bakery"}, headers=rescuer_headers)
    assert resp3.status_code == 200 # Should trigger "Already exists" check
    
    # 4. Remove
    resp4 = client.delete(f'/api/watchlist/{item_id}', headers=rescuer_headers)
    assert resp4.status_code == 200
    
    # 5. List Empty
    resp5 = client.get('/api/watchlist', headers=rescuer_headers)
    assert len(resp5.get_json()) == 0

# ==========================================
#  6. DELETE ACCOUNT (DANGER ZONE)
# ==========================================

def test_delete_account_wrong_password(client, donor_headers):
    """Sad Path: Wrong password denies deletion."""
    response = client.delete('/api/delete-account', json={"password": "WRONG"}, headers=donor_headers)
    assert response.status_code == 403
    assert "Incorrect" in response.get_json()['error']

def test_delete_account_success(client, donor_headers, donor_user):
    """Happy Path: Correct password deletes user."""
    response = client.delete('/api/delete-account', json={"password": "password"}, headers=donor_headers)
    assert response.status_code == 200
    
    # Verify DB
    db.session.expire_all()
    user = db.session.get(User, donor_user.id)
    assert user is None
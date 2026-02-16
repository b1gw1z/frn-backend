import pytest
import json
from datetime import datetime, timedelta
from models import Message, User, Donation, Contact
from extensions import db
from geoalchemy2.elements import WKTElement

# ==========================================
#  FIXTURES (Standard)
# ==========================================
@pytest.fixture
def clean_db():
    db.session.query(Contact).delete() # NEW
    db.session.query(Message).delete()
    db.session.query(Donation).delete()
    db.session.query(User).delete()
    db.session.commit()

@pytest.fixture
def users(client, clean_db):
    # Donor (Me)
    me = User(username="me", email="me@test.com", role="donor", organization_name="My Company", is_verified=True)
    me.set_password("password")
    
    # Partner 1 (John)
    u1 = User(username="john", email="john@test.com", role="rescuer", organization_name="John Logistics", is_verified=True)
    u1.set_password("password")
    
    # Partner 2 (Alice)
    u2 = User(username="alice", email="alice@test.com", role="rescuer", organization_name="Alice NGO", is_verified=True)
    u2.set_password("password")
    
    db.session.add_all([me, u1, u2])
    db.session.commit()
    return me, u1, u2

@pytest.fixture
def auth_headers(client, users):
    me = users[0]
    resp = client.post('/api/login', json={"email": me.email, "password": "password"})
    return {'Authorization': f'Bearer {resp.get_json()["access_token"]}'}

# ==========================================
#  TESTS
# ==========================================

def test_inbox_sorting(client, auth_headers, users):
    """Inbox should be sorted by time (Newest First)."""
    me, john, alice = users
    
    # 1. Create Donation
    d = Donation(title="Food", donor_id=me.id, quantity_kg=10, status="available")
    db.session.add(d)
    db.session.commit()
    
    # 2. John messages me (Older)
    msg1 = Message(sender_id=john.id, receiver_id=me.id, donation_id=d.id, text="Hi John here", timestamp=datetime.utcnow() - timedelta(hours=2))
    
    # 3. Alice messages me (Newer)
    msg2 = Message(sender_id=alice.id, receiver_id=me.id, donation_id=d.id, text="Hi Alice here", timestamp=datetime.utcnow() - timedelta(hours=1))
    
    db.session.add_all([msg1, msg2])
    db.session.commit()

    # 4. Fetch Inbox
    response = client.get('/api/messages/inbox', headers=auth_headers)
    data = response.get_json()
    
    # Alice should be index 0 because she is newer
    assert data[0]['partner_name'] == "Alice NGO"
    assert data[1]['partner_name'] == "John Logistics"

def test_nickname_and_search(client, auth_headers, users):
    """Set nickname and search by it."""
    me, john, alice = users
    d = Donation(title="Rice", donor_id=me.id, quantity_kg=10, status="available")
    db.session.add(d)
    db.session.commit()
    
    # Chat exists with John
    msg = Message(sender_id=john.id, receiver_id=me.id, donation_id=d.id, text="Hola", timestamp=datetime.utcnow())
    db.session.add(msg)
    db.session.commit()

    # 1. Set Nickname for John -> "Fast Driver"
    client.post('/api/contacts/nickname', json={
        "contact_user_id": john.id,
        "nickname": "Fast Driver"
    }, headers=auth_headers)

    # 2. Check Inbox (Should see "Fast Driver", NOT "John Logistics")
    response = client.get('/api/messages/inbox', headers=auth_headers)
    data = response.get_json()
    assert data[0]['partner_name'] == "Fast Driver"
    assert data[0]['partner_real_name'] == "John Logistics" # Still available if needed

    # 3. Search by Nickname ("Fast")
    resp_search = client.get('/api/messages/inbox?search=fast', headers=auth_headers)
    assert len(resp_search.get_json()) == 1

    # 4. Search by Original Name ("John") - Should STILL work
    resp_search_real = client.get('/api/messages/inbox?search=john', headers=auth_headers)
    assert len(resp_search_real.get_json()) == 1
    
    # 5. Search by Random string - Should fail
    resp_fail = client.get('/api/messages/inbox?search=xyz', headers=auth_headers)
    assert len(resp_fail.get_json()) == 0
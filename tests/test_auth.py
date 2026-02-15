import json

def test_register_donor_success(client):
    """
    GIVEN a running app
    WHEN a valid Donor registers
    THEN the response should be 201 Created
    """
    # 1. Define the fake user data
    payload = {
        "email": "hotel_test@example.com",
        "password": "securepassword",
        "role": "donor",
        "organization_name": "Test Hotel",
        "registration_number": "CAC-TEST-999",
        "business_type": "Hospitality",
        "latitude": 6.5244,
        "longitude": 3.3792
    }

    # 2. Send a fake POST request to your API
    response = client.post('/api/register', 
                           data=json.dumps(payload),
                           content_type='application/json')

    # 3. Check the result
    # We expect status code 201 (Created)
    assert response.status_code == 201
    
    # We expect the success message in the JSON response
    data = json.loads(response.data)
    assert "Registration successful" in data['message']
# test_campaign_api.py
# Test script for Campaign APIs

import requests
import json
import os
import time

BASE_URL = "http://127.0.0.1:8000/api"

# First, you need to login and get a token
def get_auth_token():
    """Login and get auth token"""
    print("Getting auth token...")
    response = requests.post(f"{BASE_URL}/auth/login/", json={
        "username": "hemy7egr",  # Use your test username
        "password": "TestPass123!"  # Use your test password
    })
    if response.status_code == 200:
        token = response.json()['token']
        print(f"✅ Got token: {token[:20]}...")
        return token
    else:
        print(f"❌ Login failed: {response.json()}")
        return None

def test_create_campaign(token):
    """Test creating a campaign with file upload"""
    print("\n" + "="*50)
    print("Testing CREATE CAMPAIGN with file upload...")
    print("="*50)
    
#     # Prepare the file
#     # Make sure you have sample_campaign.csv in your current directory
#     if not os.path.exists('sample_campaign.csv'):
#         print("❌ sample_campaign.csv not found! Creating one...")
#         # Create a sample CSV
#         csv_content = """phone,has_variables,variables,has_media,media_url
# +919876543210,true,"[""John"", ""Discount2024""]",false,
# +919876543211,true,"[""Alice"", ""Welcome2024""]",true,https://example.com/image1.jpg
# +919876543212,false,,false,
# +919876543213,true,"[""Bob"", ""Special50""]",true,https://example.com/image2.jpg
# +919876543214,false,,false,"""
        
#         with open('sample_campaign.csv', 'w') as f:
#             f.write(csv_content)
#         print("✅ Created sample_campaign.csv")
    
    # Upload file and create campaign
    headers = {
        "Authorization": f"Token {token}"
    }
    
    with open('tests/sample_campaign.csv', 'rb') as f:
        files = {'file': ('sample_campaign.csv', f, 'text/csv')}
        data = {'template_name': 'welcome_message_template'}
        
        response = requests.post(
            f"{BASE_URL}/campaigns/",
            headers=headers,
            files=files,
            data=data
        )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        campaign_id = response.json()['campaign']['id']
        print(f"✅ Campaign created with ID: {campaign_id}")
        return campaign_id
    return None

def test_list_campaigns(token):
    """Test listing campaigns"""
    print("\n" + "="*50)
    print("Testing LIST CAMPAIGNS...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(f"{BASE_URL}/campaigns/", headers=headers)
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    
    if 'results' in data:
        print(f"Found {len(data['results'])} campaigns:")
        for campaign in data['results']:
            print(f"  - ID: {campaign['id']}, Template: {campaign['template_name']}, Status: {campaign['status']}")
    else:
        print(f"Response: {json.dumps(data, indent=2)}")

def test_get_campaign_details(token, campaign_id):
    """Test getting campaign details"""
    print("\n" + "="*50)
    print(f"Testing GET CAMPAIGN DETAILS (ID: {campaign_id})...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(f"{BASE_URL}/campaigns/{campaign_id}/", headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_validate_file(token):
    """Test file validation endpoint"""
    print("\n" + "="*50)
    print("Testing FILE VALIDATION...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    
    with open('tests/sample_campaign.csv', 'rb') as f:
        files = {'file': ('tests/sample_campaign.csv', f, 'text/csv')}
        response = requests.post(
            f"{BASE_URL}/validate-file/",
            headers=headers,
            files=files
        )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_campaign_stats(token):
    """Test getting campaign statistics"""
    print("\n" + "="*50)
    print("Testing CAMPAIGN STATISTICS...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(f"{BASE_URL}/stats/", headers=headers)
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_start_campaign(token, campaign_id):
    """Test starting a campaign"""
    print("\n" + "="*50)
    print(f"Testing START CAMPAIGN (ID: {campaign_id})...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    
    # Wait a bit for file processing to complete
    print("Waiting for file processing to complete...")
    time.sleep(3)
    
    response = requests.post(
        f"{BASE_URL}/campaigns/{campaign_id}/start/",
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_pause_campaign(token, campaign_id):
    """Test pausing a campaign"""
    print("\n" + "="*50)
    print(f"Testing PAUSE CAMPAIGN (ID: {campaign_id})...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.post(
        f"{BASE_URL}/campaigns/{campaign_id}/pause/",
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_get_campaign_messages(token, campaign_id):
    """Test getting campaign messages"""
    print("\n" + "="*50)
    print(f"Testing GET CAMPAIGN MESSAGES (ID: {campaign_id})...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(
        f"{BASE_URL}/campaigns/{campaign_id}/messages/",
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    data = response.json()
    
    if 'results' in data:
        print(f"Found {len(data['results'])} messages")
        for msg in data['results'][:3]:  # Show first 3
            print(f"  - Phone: {msg['phone_number']}, Status: {msg['status']}")
    else:
        print(f"Response: {json.dumps(data, indent=2)}")

def test_get_campaign_statistics(token, campaign_id):
    """Test getting detailed campaign statistics"""
    print("\n" + "="*50)
    print(f"Testing GET CAMPAIGN STATISTICS (ID: {campaign_id})...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(
        f"{BASE_URL}/campaigns/{campaign_id}/statistics/",
        headers=headers
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def run_all_tests():
    """Run all campaign API tests"""
    print("\n" + "#"*50)
    print("# CAMPAIGN API TEST SUITE")
    print("#"*50)
    
    # Get auth token
    token = get_auth_token()
    if not token:
        print("❌ Cannot proceed without auth token")
        return
    
    # Test file validation
    test_validate_file(token)
    
    # Create a campaign
    campaign_id = test_create_campaign(token)
    
    if campaign_id:
        # Test various endpoints
        test_get_campaign_details(token, campaign_id)
        test_list_campaigns(token)
        test_campaign_stats(token)
        
        # Test campaign operations
        test_start_campaign(token, campaign_id)
        test_get_campaign_messages(token, campaign_id)
        test_get_campaign_statistics(token, campaign_id)
        test_pause_campaign(token, campaign_id)
    
    print("\n" + "#"*50)
    print("# TEST SUITE COMPLETED")
    print("#"*50)

if __name__ == "__main__":
    run_all_tests()

import requests
import json
import random
import string

BASE_URL = "http://127.0.0.1:8000/api/auth"

def generate_random_username():
    """Generate random username for testing"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def test_signup():
    """Test user signup"""
    print("\n" + "="*50)
    print("Testing SIGNUP...")
    print("="*50)
    
    username = generate_random_username()
    data = {
        "username": username,
        "email": f"{username}@example.com",
        "password": "TestPass123!",
        "password2": "TestPass123!",
        "first_name": "Test",
        "last_name": "User"
    }
    
    response = requests.post(f"{BASE_URL}/signup/", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        return response.json()['token'], username
    return None, None

def test_login(username, password):
    """Test user login"""
    print("\n" + "="*50)
    print("Testing LOGIN...")
    print("="*50)
    
    data = {
        "username": username,
        "password": password
    }
    
    response = requests.post(f"{BASE_URL}/login/", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        return response.json()['token']
    return None

def test_get_user_profile(token):
    """Test getting user profile"""
    print("\n" + "="*50)
    print("Testing GET USER PROFILE...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(f"{BASE_URL}/user/", headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_update_profile(token):
    """Test updating user profile"""
    print("\n" + "="*50)
    print("Testing UPDATE PROFILE...")
    print("="*50)
    
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    data = {
        "first_name": "Updated",
        "last_name": "Name"
    }
    
    response = requests.put(f"{BASE_URL}/user/", headers=headers, json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_verify_token(token):
    """Test token verification"""
    print("\n" + "="*50)
    print("Testing VERIFY TOKEN...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.get(f"{BASE_URL}/verify-token/", headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_logout(token):
    """Test user logout"""
    print("\n" + "="*50)
    print("Testing LOGOUT...")
    print("="*50)
    
    headers = {"Authorization": f"Token {token}"}
    response = requests.post(f"{BASE_URL}/logout/", headers=headers)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def test_invalid_login():
    """Test invalid login"""
    print("\n" + "="*50)
    print("Testing INVALID LOGIN...")
    print("="*50)
    
    data = {
        "username": "wronguser",
        "password": "wrongpass"
    }
    
    response = requests.post(f"{BASE_URL}/login/", json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")

def run_all_tests():
    """Run all authentication tests"""
    print("\n" + "#"*50)
    print("# AUTHENTICATION API TEST SUITE")
    print("#"*50)
    
    # Test signup
    token, username = test_signup()
    
    if token:
        print(f"\n✅ Signup successful! Token: {token[:20]}...")
        
        # Test login
        login_token = test_login(username, "TestPass123!")
        
        if login_token:
            print(f"\n✅ Login successful! Token: {login_token[:20]}...")
            
            # Test authenticated endpoints
            test_get_user_profile(login_token)
            test_update_profile(login_token)
            test_verify_token(login_token)
            test_logout(login_token)
            
            # Test token after logout (should fail)
            print("\n" + "="*50)
            print("Testing TOKEN AFTER LOGOUT (should fail)...")
            print("="*50)
            test_verify_token(login_token)
    
    # Test invalid login
    test_invalid_login()
    
    print("\n" + "#"*50)
    print("# TEST SUITE COMPLETED")
    print("#"*50)

if __name__ == "__main__":
    run_all_tests()
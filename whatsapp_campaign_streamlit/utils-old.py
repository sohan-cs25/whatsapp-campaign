import requests

API_BASE = "http://localhost:8000/api/auth"  # Change if hosted elsewhere

def signup_user(username, email, password):
    payload = {
        "username": username,
        "email": email,
        "password": password
    }
    return requests.post(f"{API_BASE}/signup/", json=payload)

def login_user(identifier, password):
    payload = {
        "username": identifier,  # Assuming the API handles email or username under "username"
        "password": password
    }
    return requests.post(f"{API_BASE}/login/", json=payload)

def logout_user(token):
    headers = {"Authorization": f"Token {token}"}
    return requests.post(f"{API_BASE}/logout/", headers=headers)

def get_user_profile(token):
    headers = {"Authorization": f"Token {token}"}
    return requests.get(f"{API_BASE}/user/", headers=headers)


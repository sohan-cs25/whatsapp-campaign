
import streamlit as st
from components.api_client import APIClient
import time

def init_session_state():
    """Initialize session state variables"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'auth_token' not in st.session_state:
        st.session_state.auth_token = None
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'login_time' not in st.session_state:
        st.session_state.login_time = None

def check_authentication():
    """Check if user is authenticated"""
    init_session_state()
    return st.session_state.authenticated

def login_form():
    """Display login form"""
    st.markdown("""
    <style>
    .auth-container {
        max-width: 400px;
        margin: auto;
        padding: 2rem;
        border-radius: 10px;
        background: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("### 🔐 Login")
        st.markdown("---")
        
        with st.form("login_form"):
            username = st.text_input("Username or Email", placeholder="Enter your username or email")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            
            col_login, col_signup = st.columns(2)
            with col_login:
                login_button = st.form_submit_button("Login", type="primary")
            with col_signup:
                signup_button = st.form_submit_button("Sign Up")
            
            if login_button:
                if username and password:
                    with st.spinner("Logging in..."):
                        api = APIClient()
                        response = api.login(username, password)
                        
                        if response.get('success'):
                            st.session_state.authenticated = True
                            st.session_state.auth_token = response.get('token')
                            st.session_state.user = response.get('user')
                            st.session_state.login_time = time.time()
                            st.success("Login successful!")
                            st.rerun()
                        else:
                            st.error(response.get('error', 'Invalid credentials'))
                else:
                    st.error("Please enter both username and password")
            
            if signup_button:
                st.session_state.show_signup = True
                st.rerun()

def signup_form():
    """Display signup form"""
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("### 📝 Sign Up")
        st.markdown("---")
        
        with st.form("signup_form"):
            col_first, col_last = st.columns(2)
            with col_first:
                first_name = st.text_input("First Name", placeholder="John")
            with col_last:
                last_name = st.text_input("Last Name", placeholder="Doe")
            
            username = st.text_input("Username*", placeholder="Choose a username")
            email = st.text_input("Email*", placeholder="your@email.com")
            password = st.text_input("Password*", type="password", placeholder="Create a password")
            password2 = st.text_input("Confirm Password*", type="password", placeholder="Confirm your password")
            
            col_signup, col_back = st.columns(2)
            with col_signup:
                signup_button = st.form_submit_button("Create Account", type="primary")
            with col_back:
                back_button = st.form_submit_button("Back to Login")
            
            if signup_button:
                if username and email and password and password2:
                    if password != password2:
                        st.error("Passwords do not match")
                    else:
                        with st.spinner("Creating account..."):
                            api = APIClient()
                            response = api.signup(username, email, password, password2, first_name, last_name)
                            
                            if response.get('success'):
                                st.success("Account created successfully! Please login.")
                                st.session_state.show_signup = False
                                time.sleep(2)
                                st.rerun()
                            else:
                                errors = response.get('errors', {})
                                for field, error_list in errors.items():
                                    for error in error_list:
                                        st.error(f"{field}: {error}")
                else:
                    st.error("Please fill all required fields")
            
            if back_button:
                st.session_state.show_signup = False
                st.rerun()

def logout():
    """Logout user"""
    api = APIClient()
    api.logout()
    
    st.session_state.authenticated = False
    st.session_state.auth_token = None
    st.session_state.user = None
    st.session_state.login_time = None
    st.rerun()

def require_auth():
    """Decorator to require authentication for pages"""
    if not check_authentication():
        st.warning("Please login to access this page")
        st.stop()

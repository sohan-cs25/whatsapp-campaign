import streamlit as st
from utils import signup_user, login_user, get_user_profile

st.set_page_config(page_title="AuthApp", page_icon="🔐", layout="centered")

# --- SESSION STATE INIT ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "token" not in st.session_state:
    st.session_state.token = None
if "username" not in st.session_state:
    st.session_state.username = ""

# --- LOGGED IN VIEW ---
def show_main_app():
    st.success(f"Welcome, {st.session_state.username}!")
    if st.button("Logout"):
        st.session_state.authenticated = False
        st.session_state.token = None
        st.session_state.username = ""
        st.experimental_rerun()

# --- LOGIN FORM ---
def login_form():
    st.subheader("🔐 Login")
    identifier = st.text_input("Username or Email", key="login_username")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login", key="login_button"):
        if identifier and password:
            res = login_user(identifier, password)
            if res.status_code == 200:
                token = res.json().get("token")
                profile = get_user_profile(token)
                if profile.status_code == 200:
                    st.session_state.token = token
                    st.session_state.username = profile.json().get("username")
                    st.session_state.authenticated = True
                    st.success("Login successful!")
                    st.rerun()
                else:
                    st.error("Failed to fetch user profile.")
            else:
                st.error("Login failed. Please check your credentials.")

# --- SIGN UP FORM ---
def signup_form():
    st.subheader("📝 Sign Up")
    username = st.text_input("Username", key="signup_username")
    email = st.text_input("Email", key="signup_email")
    password = st.text_input("Password", type="password", key="signup_password")
    if st.button("Sign Up", key="signup_button"):
        if username and email and password:
            res = signup_user(username, email, password)
            if res.status_code == 201:
                st.success("Signup successful. You can now login.")
            else:
                st.error(f"Signup failed: {res.text}")


# --- PAGE LOGIC ---
def auth_page():
    st.title("🚪 Welcome to AuthApp")

    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        login_form()
    with tab2:
        signup_form()

# --- MAIN APP LOGIC ---
if st.session_state.authenticated:
    show_main_app()
else:
    auth_page()


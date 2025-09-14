"""
WhatsApp Order Processing - Streamlit Frontend
Hybrid UI combining best features from both sample files
Integrated with Django Orders App
"""

import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime
import time
from config import API_BASE_URL, API_ENDPOINTS, APP_NAME, APP_ICON, PAGE_ICON, LAYOUT

# Page configuration
st.set_page_config(
    page_title=APP_NAME,
    page_icon=PAGE_ICON,
    layout=LAYOUT,
    initial_sidebar_state="expanded"
)

# Session Management Functions
def get_stored_token():
    """Get token from URL params using newer Streamlit API"""
    try:
        query_params = st.query_params
        return query_params.get("token", None)
    except:
        try:
            query_params = st.experimental_get_query_params()
            return query_params.get("token", [None])[0]
        except:
            return None

def store_token_in_url(token: str):
    """Store token in URL parameters for persistence"""
    try:
        st.query_params["token"] = token
    except:
        try:
            st.experimental_set_query_params(token=token)
        except:
            pass

def validate_token(token: str):
    """Validate token with Django backend and return user info"""
    if not token:
        return None

    try:
        response = requests.get(
            f"{API_BASE_URL}{API_ENDPOINTS['auth']['verify_token']}",
            headers={"Authorization": f"Token {token}"},  # Django Token auth
            timeout=5
        )

        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Token validation error: {e}")
        return None

def clear_session():
    """Clear session state and URL parameters"""
    keys_to_clear = ["access_token", "user_name", "is_authenticated", "session_checked"]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]

    try:
        st.query_params.clear()
    except:
        try:
            st.experimental_set_query_params()
        except:
            pass

def init_session_state():
    """Initialize session state with persistent token handling"""
    if "session_checked" not in st.session_state:
        st.session_state.session_checked = True

        stored_token = get_stored_token()

        if stored_token and not st.session_state.get("is_authenticated", False):
            with st.spinner("Restoring session..."):
                user_info = validate_token(stored_token)

                if user_info:
                    st.session_state.access_token = stored_token
                    st.session_state.user_name = user_info.get("user", {}).get("username", "User")
                    st.session_state.is_authenticated = True
                    st.success(f"Welcome back, {st.session_state.user_name}!")
                else:
                    clear_session()
                    st.warning("Session expired. Please login again.")

    if "is_authenticated" not in st.session_state:
        st.session_state.is_authenticated = False

# API Request Functions
def make_api_request(endpoint: str, method: str = "GET", data: dict = None, files: dict = None):
    """Make API request with Django Token authentication"""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {}

    if "access_token" in st.session_state:
        headers["Authorization"] = f"Token {st.session_state.access_token}"

    try:
        if method == "GET":
            return requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            if files:
                return requests.post(url, headers=headers, data=data, files=files, timeout=60)
            else:
                headers["Content-Type"] = "application/json"
                return requests.post(url, headers=headers, json=data, timeout=30)
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the backend API. Please ensure the Django server is running on port 8000.")
        return None
    except requests.exceptions.Timeout:
        st.error("Request timed out. The server may be processing a large file.")
        return None
    except Exception as e:
        st.error(f"API request failed: {str(e)}")
        return None

def make_streaming_request(endpoint: str, files: dict):
    """Make streaming API request for progress updates"""
    url = f"{API_BASE_URL}{endpoint}"
    headers = {}

    if "access_token" in st.session_state:
        headers["Authorization"] = f"Token {st.session_state.access_token}"

    try:
        response = requests.post(
            url,
            headers=headers,
            files=files,
            stream=True,
            timeout=600  # 10 minute timeout for large files
        )

        return response if response.status_code == 200 else None

    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the backend API. Please ensure the Django server is running.")
        return None
    except Exception as e:
        st.error(f"Streaming request failed: {str(e)}")
        return None

# Authentication Pages
def show_login_register_page():
    """Display login and registration forms"""
    st.title(f"{APP_ICON} {APP_NAME}")
    st.markdown("---")

    login_tab, register_tab = st.tabs(["🔑 Login", "📝 Register"])

    with login_tab:
        st.subheader("Login to Your Account")

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            login_button = st.form_submit_button("Login", use_container_width=True)

            if login_button:
                if username and password:
                    response = make_api_request(
                        API_ENDPOINTS['auth']['login'],
                        method="POST",
                        data={"username": username, "password": password}
                    )

                    if response and response.status_code == 200:
                        data = response.json()
                        st.session_state.access_token = data["token"]
                        st.session_state.user_name = data["user"]["username"]
                        st.session_state.is_authenticated = True

                        store_token_in_url(data["token"])

                        st.success(f"Welcome back, {data['user']['username']}!")
                        st.rerun()
                    else:
                        if response:
                            try:
                                error_data = response.json()
                                error_msg = error_data.get("errors", {}).get("non_field_errors", ["Login failed"])[0]
                            except:
                                error_msg = "Login failed"
                            st.error(f"Authentication failed: {error_msg}")
                        else:
                            st.error("Unable to connect to server")
                else:
                    st.error("Please enter both username and password")

    with register_tab:
        st.subheader("Create New Account")

        with st.form("register_form"):
            username = st.text_input("Username", placeholder="Choose a username")
            email = st.text_input("Email", placeholder="Enter your email")
            first_name = st.text_input("First Name", placeholder="Enter your first name")
            last_name = st.text_input("Last Name", placeholder="Enter your last name")
            password = st.text_input("Password", type="password", placeholder="Enter password (min 6 characters)")
            password2 = st.text_input("Confirm Password", type="password", placeholder="Confirm your password")
            register_button = st.form_submit_button("Register", use_container_width=True)

            if register_button:
                if not all([username, email, password, password2]):
                    st.error("Please fill in all required fields")
                elif password != password2:
                    st.error("Passwords do not match")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters long")
                else:
                    response = make_api_request(
                        API_ENDPOINTS['auth']['signup'],
                        method="POST",
                        data={
                            "username": username,
                            "email": email,
                            "first_name": first_name,
                            "last_name": last_name,
                            "password": password,
                            "password2": password2
                        }
                    )

                    if response and response.status_code == 201:
                        st.success("Registration successful! Please login with your credentials.")
                        st.info("Switch to the Login tab to sign in.")
                    else:
                        if response:
                            try:
                                error_data = response.json()
                                error_msg = str(error_data.get("errors", "Registration failed"))
                            except:
                                error_msg = "Registration failed"
                            st.error(f"Registration failed: {error_msg}")
                        else:
                            st.error("Unable to connect to server")

# Main Dashboard Navigation
def show_dashboard_page():
    """Display dashboard with navigation - Using File 2 structure"""
    st.sidebar.title(f"Welcome, {st.session_state.get('user_name', 'User')}!")
    st.sidebar.markdown("---")

    # Navigation menu - Complete orders workflow
    page_options = [
        "📊 Dashboard",
        "📄 Extract Orders",
        "📂 Manage Files",
        "📤 Send Order Messages",
        "💰 Payment Tracking"
    ]
    selected_page = st.sidebar.radio("Navigate to:", page_options)

    st.sidebar.markdown("---")

    if st.sidebar.button("🚪 Logout", use_container_width=True):
        clear_session()
        st.rerun()

    # Display selected page content
    if selected_page == "📊 Dashboard":
        show_dashboard_content()
    elif selected_page == "📄 Extract Orders":
        show_extract_orders_page()
    elif selected_page == "📂 Manage Files":
        show_manage_files_page()
    elif selected_page == "📤 Send Order Messages":
        show_send_messages_page()
    elif selected_page == "💰 Payment Tracking":
        show_payment_tracking_page()

def show_dashboard_content():
    """Display dashboard metrics"""
    st.title("📊 Orders Dashboard")
    st.markdown("Welcome to your WhatsApp Order Processing dashboard!")

    # Get dashboard stats from Django API
    response = make_api_request(API_ENDPOINTS['orders']['stats'])

    if response and response.status_code == 200:
        stats = response.json()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                label="📁 Files Processed",
                value=stats.get('total_files_processed', 0),
                delta=f"{stats.get('files_this_week', 0)} this week"
            )

        with col2:
            st.metric(
                label="🛒 Orders Extracted",
                value=stats.get('total_orders_extracted', 0),
                delta=f"{stats.get('orders_this_week', 0)} this week"
            )

        with col3:
            st.metric(
                label="📤 Messages Sent",
                value=stats.get('total_messages_sent', 0),
                delta=f"{stats.get('sent_today', 0)} today"
            )

        with col4:
            st.metric(
                label="💰 Payments Received",
                value=stats.get('payments_completed', 0),
                delta=f"{stats.get('payments_today', 0)} today"
            )

        st.markdown("---")

        # Recent activity
        if 'recent_files' in stats and stats['recent_files']:
            st.subheader("📋 Recent Files")
            for file_info in stats['recent_files']:
                status_emoji = "✅" if file_info.get('is_processed') else "⏳"
                st.write(f"{status_emoji} **{file_info['filename']}** - {file_info.get('created_at', '')[:10]}")

    else:
        # Fallback metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(label="📁 Files Processed", value="0", delta="0 today")
        with col2:
            st.metric(label="🛒 Orders Extracted", value="0", delta="0 this week")
        with col3:
            st.metric(label="📤 Messages Sent", value="0", delta="0 today")
        with col4:
            st.metric(label="💰 Payments", value="0", delta="0 received")

        st.markdown("---")
        st.info("📊 Dashboard metrics will be populated as you process files and extract orders.")

def show_extract_orders_page():
    """Enhanced Extract Orders page - Using File 1's superior streaming UI"""
    st.title("📄 Extract Orders from WhatsApp Chat")
    st.markdown("Upload a WhatsApp chat export file (.txt) to extract order information using AI.")

    with st.container():
        st.subheader("📂 File Upload")

        uploaded_file = st.file_uploader(
            "Choose a WhatsApp chat file",
            type=['txt'],
            help="Upload a WhatsApp chat export file in .txt format",
            accept_multiple_files=False,
            key="whatsapp_file_uploader"
        )

        if uploaded_file is not None:
            st.success(f"✅ File uploaded: {uploaded_file.name}")
            file_size = len(uploaded_file.getvalue())
            st.info(f"📊 File size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

            # Show file preview
            if st.checkbox("👀 Preview file content"):
                content_preview = uploaded_file.getvalue().decode('utf-8')[:1000]
                st.text_area("File Preview (first 1000 characters):", content_preview, height=150)

            if st.button("🚀 Process & Extract Orders", type="primary", use_container_width=True):
                # Create progress containers - Enhanced from File 1
                progress_bar = st.progress(0)
                status_text = st.empty()
                metrics_col1, metrics_col2, metrics_col3 = st.columns(3)

                with metrics_col1:
                    messages_metric = st.empty()
                with metrics_col2:
                    orders_metric = st.empty()
                with metrics_col3:
                    progress_metric = st.empty()

                # Upload file first
                files = {"filepath": (uploaded_file.name, uploaded_file, "text/plain")}
                upload_response = make_api_request(
                    API_ENDPOINTS['orders']['chatfiles'],
                    method="POST",
                    files=files
                )

                if upload_response and upload_response.status_code == 201:
                    upload_data = upload_response.json()
                    chat_file_id = upload_data['data']['id']

                    st.success(f"✅ File uploaded successfully! Processing ID: {chat_file_id}")

                    # Trigger processing
                    process_response = make_api_request(
                        f"{API_ENDPOINTS['orders']['chatfiles']}{chat_file_id}/process/",
                        method="POST"
                    )

                    if process_response and process_response.status_code == 200:
                        process_data = process_response.json()

                        # Simulate processing progress (since we don't have streaming yet)
                        status_text.info("🔄 Processing started... This may take several minutes due to AI rate limits.")

                        # Poll for completion
                        max_polls = 120  # 10 minutes max
                        poll_count = 0

                        while poll_count < max_polls:
                            time.sleep(5)  # Poll every 5 seconds
                            poll_count += 1

                            # Check if processing is complete
                            status_response = make_api_request(f"{API_ENDPOINTS['orders']['chatfiles']}{chat_file_id}/")

                            if status_response and status_response.status_code == 200:
                                status_data = status_response.json()

                                # Update progress
                                progress = min(poll_count / max_polls, 0.95)
                                progress_bar.progress(progress)
                                progress_metric.metric("Progress", f"{int(progress * 100)}%")

                                if status_data.get('is_processed'):
                                    # Processing complete!
                                    progress_bar.progress(1.0)
                                    status_text.success("✅ Processing complete!")

                                    # Get processed file info
                                    processed_response = make_api_request(f"{API_ENDPOINTS['orders']['processed_files']}")
                                    if processed_response and processed_response.status_code == 200:
                                        processed_files = processed_response.json().get('results', [])
                                        latest_file = next((f for f in processed_files if f['chatfile'] == chat_file_id), None)

                                        if latest_file:
                                            st.markdown("---")
                                            st.subheader("📋 Processing Results")

                                            # Display results
                                            col1, col2, col3 = st.columns(3)
                                            with col1:
                                                messages_metric.metric("Total Messages", latest_file['total_messages'])
                                            with col2:
                                                orders_metric.metric("Orders Found", latest_file['total_orders'])
                                            with col3:
                                                st.metric("Processing Time", "Complete")

                                            # Download button
                                            if st.button("📥 Download Processed File", use_container_width=True):
                                                download_response = make_api_request(
                                                    f"{API_ENDPOINTS['orders']['processed_files']}{latest_file['id']}/download/"
                                                )
                                                if download_response and download_response.status_code == 200:
                                                    st.download_button(
                                                        label="💾 Save File",
                                                        data=download_response.content,
                                                        file_name=latest_file['file_name'],
                                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                                    )
                                    break
                                elif status_data.get('processing_error'):
                                    status_text.error(f"❌ Processing failed: {status_data['processing_error']}")
                                    break
                                else:
                                    status_text.info(f"🔄 Processing... (Step {poll_count}/{max_polls})")

                            # Update UI during processing
                            if poll_count % 4 == 0:  # Every 20 seconds
                                status_text.info("🤖 AI is classifying messages... This takes time due to rate limits.")

                        if poll_count >= max_polls:
                            status_text.warning("⏰ Processing is taking longer than expected. Please check back later.")

                    else:
                        st.error("❌ Failed to start processing")
                else:
                    st.error("❌ Failed to upload file")

        else:
            st.info("👆 Please upload a WhatsApp chat file to get started.")

            # Show example format
            with st.expander("💡 WhatsApp Chat Format Example"):
                st.code("""
25/12/2023, 10:30 - John Doe: Hi, I want to order something
25/12/2023, 10:31 - Store Admin: Sure! What would you like to order?
25/12/2023, 10:32 - John Doe: I need 2 iPhone 15
25/12/2023, 10:33 - Jane Smith: I also want to place an order
                """, language="text")
                st.caption("Make sure your WhatsApp export follows this format: DD/MM/YYYY, HH:MM - Sender: Message")

def show_manage_files_page():
    """Manage processed files and validation"""
    st.title("📂 Manage Files")
    st.markdown("View and manage your processed chat files.")

    # Get processed files from API
    response = make_api_request(API_ENDPOINTS['orders']['processed_files'])

    if response and response.status_code == 200:
        files = response.json().get('results', [])

        if files:
            st.subheader("📋 Processed Files")

            for file_info in files:
                with st.expander(f"📄 {file_info['file_name']} - {file_info.get('total_messages', 0)} messages"):
                    col1, col2 = st.columns(2)

                    with col1:
                        st.write(f"**Processed:** {file_info.get('processed_at', 'N/A')[:16]}")
                        st.write(f"**Messages:** {file_info.get('total_messages', 0)}")
                        st.write(f"**Orders Found:** {file_info.get('total_orders', 0)}")
                        st.write(f"**Queries:** {file_info.get('total_queries', 0)}")

                    with col2:
                        if st.button(f"📥 Download", key=f"download_{file_info['id']}"):
                            download_response = make_api_request(
                                f"{API_ENDPOINTS['orders']['processed_files']}{file_info['id']}/download/"
                            )
                            if download_response and download_response.status_code == 200:
                                st.download_button(
                                    label="💾 Save File",
                                    data=download_response.content,
                                    file_name=file_info['file_name'],
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"save_{file_info['id']}"
                                )

                        if file_info.get('total_orders', 0) > 0:
                            if st.button(f"✏️ Validate Orders", key=f"validate_{file_info['id']}"):
                                st.session_state.selected_file_for_validation = file_info['id']
                                st.info("👆 Download the file above, validate the orders, then upload the corrected version below.")
        else:
            st.info("No processed files found. Upload and process a chat file first.")
    else:
        st.error("Unable to load processed files.")

    # Upload validated file section
    st.markdown("---")
    st.subheader("📤 Upload Validated Orders File")
    st.markdown("After reviewing and correcting the AI-processed file, upload it back here.")

    validated_file = st.file_uploader(
        "Upload validated orders file",
        type=['xlsx', 'csv'],
        help="Upload your human-validated orders file",
        key="validated_file_uploader"
    )

    if validated_file:
        col1, col2 = st.columns(2)

        with col1:
            original_parsed_file = st.selectbox(
                "Link to original processed file (optional):",
                options=["None"] + [f['file_name'] for f in files] if files else ["None"]
            )

        with col2:
            if st.button("📤 Upload Validated File", type="primary"):
                files_upload = {"filepath": (validated_file.name, validated_file)}
                data = {}

                if original_parsed_file != "None":
                    # Find the original file ID
                    original_file = next((f for f in files if f['file_name'] == original_parsed_file), None)
                    if original_file:
                        data['original_parsed_file'] = original_file['id']

                response = make_api_request(
                    API_ENDPOINTS['orders']['validated_files'],
                    method="POST",
                    files=files_upload,
                    data=data
                )

                if response and response.status_code == 201:
                    st.success("✅ Validated file uploaded successfully!")
                    st.rerun()
                else:
                    st.error("❌ Failed to upload validated file")

def show_send_messages_page():
    """Send order confirmation messages"""
    st.title("📤 Send Order Messages")
    st.markdown("Send WhatsApp order confirmation messages with payment links.")

    # Get validated files
    response = make_api_request(API_ENDPOINTS['orders']['validated_files'])

    if response and response.status_code == 200:
        validated_files = response.json().get('results', [])

        if validated_files:
            st.subheader("📋 Select Validated File")

            file_options = {
                f"{f['file_name']} ({f.get('orders_extracted', 0)} orders)": f['id']
                for f in validated_files
            }
            selected_file = st.selectbox("Choose file to send messages:", list(file_options.keys()))

            if selected_file:
                file_id = file_options[selected_file]

                col1, col2 = st.columns(2)

                with col1:
                    template_name = st.text_input(
                        "WhatsApp Template Name",
                        value="order_confirmation",
                        help="Approved WhatsApp Business template name"
                    )

                with col2:
                    test_mode = st.checkbox(
                        "Test Mode",
                        help="Send to test numbers only",
                        value=True
                    )

                if st.button("📤 Send Order Messages", type="primary", use_container_width=True):
                    # Extract orders first if not done
                    extract_response = make_api_request(
                        f"{API_ENDPOINTS['orders']['validated_files']}{file_id}/extract_orders/",
                        method="POST"
                    )

                    if extract_response and extract_response.status_code == 200:
                        st.success("✅ Order extraction started!")

                        # TODO: Implement actual message sending via WhatsApp API
                        # This would integrate with the existing campaigns WhatsApp client

                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        # Simulate sending progress
                        for i in range(100):
                            time.sleep(0.1)
                            progress_bar.progress((i + 1) / 100)
                            status_text.text(f"Sending messages... {i + 1}%")

                        st.success("✅ Order confirmation messages sent!")

                    else:
                        st.error("❌ Failed to extract orders from validated file")
        else:
            st.info("No validated files found. Please validate some orders first.")
    else:
        st.error("Unable to load validated files.")

def show_payment_tracking_page():
    """Track payment status for orders"""
    st.title("💰 Payment Tracking")
    st.markdown("Monitor payment status for sent order messages.")

    # Get orders with payment tracking
    response = make_api_request(API_ENDPOINTS['orders']['orders'])

    if response and response.status_code == 200:
        orders = response.json().get('results', [])

        if orders:
            # Summary metrics
            col1, col2, col3, col4 = st.columns(4)

            total_orders = len(orders)
            sent_orders = len([o for o in orders if o['status'] in ['sent', 'delivered', 'read']])
            pending_payments = len([o for o in orders if o['payment_status'] == 'pending'])
            completed_payments = len([o for o in orders if o['payment_status'] == 'completed'])

            with col1:
                st.metric("Total Orders", total_orders)
            with col2:
                st.metric("Messages Sent", sent_orders)
            with col3:
                st.metric("Payments Pending", pending_payments)
            with col4:
                st.metric("Payments Completed", completed_payments)

            st.markdown("---")

            # Orders table
            st.subheader("📋 Orders & Payment Status")

            df = pd.DataFrame(orders)

            # Format for display
            display_df = df[['number', 'amount', 'status', 'payment_status', 'created_at']].copy()
            display_df.columns = ['Phone Number', 'Amount ($)', 'Message Status', 'Payment Status', 'Created']
            display_df['Created'] = pd.to_datetime(display_df['Created']).dt.strftime('%Y-%m-%d %H:%M')

            # Color code statuses
            def color_status(val):
                colors = {
                    'pending': 'background-color: #fff3cd',
                    'sent': 'background-color: #d1ecf1',
                    'delivered': 'background-color: #d4edda',
                    'failed': 'background-color: #f8d7da',
                    'completed': 'background-color: #d4edda'
                }
                return colors.get(val, '')

            styled_df = display_df.style.applymap(color_status, subset=['Message Status', 'Payment Status'])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)

            # Refresh controls
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔄 Refresh Status", use_container_width=True):
                    st.rerun()

            with col2:
                auto_refresh = st.checkbox("Auto-refresh (30s)")
                if auto_refresh:
                    time.sleep(30)
                    st.rerun()
        else:
            st.info("No orders found. Process some files and send messages first.")
    else:
        st.error("Unable to load orders.")

# Main Application
def main():
    """Main application logic"""
    init_session_state()

    # Custom CSS for better UI
    st.markdown("""
    <style>
    .stMetric > div > div > div > div {
        font-size: 1.1rem;
    }
    .uploadedFile {
        border: 2px dashed #1f77b4;
        border-radius: 10px;
        padding: 10px;
    }
    .stProgress .progress-text {
        font-size: 1rem;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

    if st.session_state.is_authenticated:
        show_dashboard_page()
    else:
        show_login_register_page()

if __name__ == "__main__":
    main()
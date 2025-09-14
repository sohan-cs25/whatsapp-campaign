
import streamlit as st
from components.auth import check_authentication, login_form, signup_form, init_session_state
from config import APP_NAME, APP_ICON, PAGE_ICON, LAYOUT

# Page configuration
st.set_page_config(
    page_title=APP_NAME,
    page_icon=PAGE_ICON,
    layout=LAYOUT,
    initial_sidebar_state="expanded"
)

# Custom CSS for professional look
st.markdown("""
<style>
    /* Main header styling */
    .main-header {
        background: linear-gradient(90deg, #25D366 0%, #128C7E 100%);
        color: white;
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        text-align: center;
    }
    
    /* Card styling */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
        transition: transform 0.2s;
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    
    /* Button styling */
    .stButton > button {
        background: linear-gradient(90deg, #25D366 0%, #128C7E 100%);
        color: white;
        border: none;
        padding: 0.5rem 2rem;
        border-radius: 5px;
        font-weight: 600;
        transition: opacity 0.2s;
    }
    
    .stButton > button:hover {
        opacity: 0.9;
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        background-color: #f5f5f5;
    }
    
    /* Success message styling */
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

def main():
    """Main application"""
    init_session_state()
    
    if not check_authentication():
        # Show login/signup page
        st.markdown(f"""
        <div class="main-header">
            <h1>{APP_ICON} {APP_NAME}</h1>
            <p style="font-size: 1.2rem; opacity: 0.9;">Professional WhatsApp Marketing Solution</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.session_state.get('show_signup', False):
            signup_form()
        else:
            login_form()
    else:
        # User is authenticated, show main app
        # Clean navigation sidebar
        with st.sidebar:
            st.markdown("## 🔗 Navigation")
            
            # Direct page links
            if st.button("📊 Dashboard", key="nav_dashboard"):
                st.switch_page("pages/Dashboard.py")
            if st.button("➕ Create Campaign", key="nav_create"):
                st.switch_page("pages/Create_Campaign.py")
            if st.button("📈 Manage Campaigns", key="nav_campaigns"):
                st.switch_page("pages/Campaigns.py")
            
            st.markdown("---")
            
            # User info
            st.markdown(f"**👤 {st.session_state.user.get('username', 'User')}**")
            
            # Logout button
            if st.button("🚪 Logout", key="nav_logout"):
                from components.auth import logout
                logout()
        
        # Main content header
        st.markdown(f"""
        <div class="main-header">
            <h1>{APP_ICON} {APP_NAME}</h1>
            <p style="font-size: 1.2rem; opacity: 0.9;">Campaign Dashboard</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Get real metrics from API
        from components.api_client import APIClient
        api = APIClient()
        
        try:
            stats_response = api.get_stats()
            stats = stats_response.get('statistics', {}) if stats_response.get('success') else {}
        except Exception as e:
            st.error(f"Failed to load statistics: {str(e)}")
            stats = {}
        
        # Real-time metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_campaigns = stats.get('total_campaigns', 0)
            st.markdown(f"""
            <div class="metric-card">
                <h3 style="color: #25D366;">{total_campaigns}</h3>
                <p style="color: #666;">Total Campaigns</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            active_campaigns = stats.get('active_campaigns', 0)
            st.markdown(f"""
            <div class="metric-card">
                <h3 style="color: #2196F3;">{active_campaigns}</h3>
                <p style="color: #666;">Active</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            messages_sent = stats.get('total_messages_sent', 0)
            st.markdown(f"""
            <div class="metric-card">
                <h3 style="color: #4CAF50;">{messages_sent:,}</h3>
                <p style="color: #666;">Messages Sent</p>
            </div>
            """, unsafe_allow_html=True)
        
        with col4:
            success_rate = stats.get('overall_success_rate', 0)
            st.markdown(f"""
            <div class="metric-card">
                <h3 style="color: #FF9800;">{success_rate:.1f}%</h3>
                <p style="color: #666;">Success Rate</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Quick Actions
        st.markdown("---")
        st.markdown("### 🚀 Quick Actions")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("➕ Create Campaign", key="create_campaign_btn", type="primary"):
                st.switch_page("pages/Create_Campaign.py")
        with col2:
            if st.button("📈 Manage Campaigns", key="manage_campaigns_btn"):
                st.switch_page("pages/Campaigns.py")

if __name__ == "__main__":
    main()

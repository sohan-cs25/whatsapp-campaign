
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime, timedelta
from components.auth import require_auth, logout
from components.api_client import APIClient
from config import STATUS_COLORS

# Check authentication
require_auth()

# Page header
st.title("📊 Campaign Dashboard")

# Add logout button in sidebar
with st.sidebar:
    if st.button("🚪 Logout", key="dashboard_logout"):
        logout()

# Refresh button
col1, col2, col3 = st.columns([6, 1, 1])
with col3:
    if st.button("🔄 Refresh", key="dashboard_refresh"):
        st.rerun()

# Get statistics from API with error handling
api = APIClient()

try:
    stats_response = api.get_stats()
    if stats_response.get('success'):
        stats = stats_response.get('statistics', {})
    else:
        st.error("Failed to load statistics from server.")
        stats = {}
except Exception as e:
    st.error(f"Connection error: {str(e)}")
    stats = {}

try:
    campaigns_response = api.get_campaigns()
    if not campaigns_response.get('results') and campaigns_response.get('success') is False:
        st.error("Failed to load campaigns from server.")
except Exception as e:
    st.error(f"Connection error while loading campaigns: {str(e)}")
    campaigns_response = {'results': []}

# Display main metrics
st.markdown("### 📈 Overall Statistics")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Total Campaigns",
        value=stats.get('total_campaigns', 0),
        delta=None
    )

with col2:
    st.metric(
        label="Active Campaigns",
        value=stats.get('active_campaigns', 0),
        delta=None
    )

with col3:
    st.metric(
        label="Messages Sent",
        value=f"{stats.get('total_messages_sent', 0):,}",
        delta=None
    )

with col4:
    st.metric(
        label="Success Rate",
        value=f"{stats.get('overall_success_rate', 0):.1f}%",
        delta=None
    )

# Charts section
st.markdown("---")
st.markdown("### 📊 Analytics")

col1, col2 = st.columns(2)

with col1:
    # Campaign status distribution pie chart
    st.markdown("#### Campaign Status Distribution")
    
    status_data = stats.get('campaigns_by_status', {})
    if status_data:
        fig = go.Figure(data=[go.Pie(
            labels=list(status_data.keys()),
            values=list(status_data.values()),
            hole=0.3,
            marker_colors=[STATUS_COLORS.get(k, '#999') for k in status_data.keys()]
        )])
        fig.update_layout(
            height=300,
            margin=dict(t=0, b=0, l=0, r=0),
            showlegend=True
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No campaign data available")

with col2:
    # Delivery metrics
    st.markdown("#### Message Delivery Metrics")
    
    sent = stats.get('total_messages_sent', 0)
    delivered = stats.get('total_messages_delivered', 0)
    
    # Calculate failed messages properly (assuming we have this data)
    # For now, we'll use sent - delivered as an approximation
    failed = max(0, sent - delivered)
    
    delivery_data = {
        'Sent': sent,
        'Delivered': delivered,
        'Pending': failed  # This is more accurate than "Failed"
    }
    
    if delivery_data['Sent'] > 0:
        fig = go.Figure(data=[
            go.Bar(
                x=list(delivery_data.keys()),
                y=list(delivery_data.values()),
                marker_color=['#2196F3', '#4CAF50', '#FF9800']
            )
        ])
        fig.update_layout(
            height=300,
            margin=dict(t=0, b=0, l=0, r=0),
            yaxis_title="Messages",
            showlegend=False
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No message data available")

# Recent Campaigns Table
st.markdown("---")
st.markdown("### 📋 Recent Campaigns")

if campaigns_response.get('results'):
    campaigns_df = pd.DataFrame(campaigns_response['results'])
    
    # Format the dataframe for display
    display_columns = ['id', 'template_name', 'status', 'total_recipients', 
                      'sent_count', 'delivered_count', 'success_rate', 'created_at']
    
    # Filter columns that exist
    available_columns = [col for col in display_columns if col in campaigns_df.columns]
    campaigns_display = campaigns_df[available_columns].copy()
    
    # Format dates
    if 'created_at' in campaigns_display.columns:
        campaigns_display['created_at'] = pd.to_datetime(campaigns_display['created_at']).dt.strftime('%Y-%m-%d %H:%M')
    
    # Format success rate
    if 'success_rate' in campaigns_display.columns:
        campaigns_display['success_rate'] = campaigns_display['success_rate'].apply(lambda x: f"{x:.1f}%")
    
    # Rename columns for display
    campaigns_display.columns = ['ID', 'Template', 'Status', 'Recipients', 
                                'Sent', 'Delivered', 'Success Rate', 'Created'][:len(campaigns_display.columns)]
    
    # Display table with custom styling
    st.dataframe(
        campaigns_display,
        width="stretch",
        hide_index=True,
        column_config={
            "Status": st.column_config.TextColumn(
                "Status",
                help="Campaign status",
            ),
        }
    )
else:
    st.info("No campaigns found. Create your first campaign to get started!")
    if st.button("➕ Create First Campaign", key="dashboard_create_first"):
        st.switch_page("pages/Create_Campaign.py")

# Recent Activity
st.markdown("---")
st.markdown("### 📋 Recent Activity")

if campaigns_response.get('results'):
    recent_campaigns = campaigns_response['results'][:5]  # Show last 5 campaigns
    
    for campaign in recent_campaigns:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            
            with col1:
                st.write(f"**{campaign['template_name']}**")
            with col2:
                status_color = STATUS_COLORS.get(campaign['status'], '#999')
                st.markdown(f"""
                <span style="background-color: {status_color}; color: white; padding: 2px 8px; 
                            border-radius: 3px; font-size: 12px;">
                    {campaign['status'].upper()}
                </span>
                """, unsafe_allow_html=True)
            with col3:
                progress = f"{campaign['sent_count']}/{campaign['total_recipients']}"
                st.write(progress)
            with col4:
                if campaign['total_recipients'] > 0:
                    success_rate = (campaign['sent_count'] / campaign['total_recipients']) * 100
                    st.write(f"{success_rate:.1f}%")
                else:
                    st.write("0.0%")
        
        st.markdown("---")
else:
    st.info("No recent campaigns found. Create your first campaign to get started!")
    if st.button("➕ Create First Campaign", key="dashboard_create_first_recent"):
        st.switch_page("pages/Create_Campaign.py")

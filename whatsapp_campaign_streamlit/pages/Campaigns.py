# streamlit-app/pages/3_📈_Campaigns.py

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import time
import io
from components.auth import require_auth, logout
from components.api_client import APIClient
from config import STATUS_COLORS, STATUS_ICONS

# Check authentication
require_auth()

# Page header
st.title("📈 Campaign Management")

# Add logout button in sidebar
with st.sidebar:
    if st.button("🚪 Logout", key="campaigns_logout"):
        logout()
    
    st.markdown("---")
    st.markdown("### 🎯 Quick Actions")
    if st.button("➕ Create New Campaign", key="campaigns_create_new"):
        st.switch_page("pages/Create_Campaign.py")
    if st.button("📊 View Dashboard", key="campaigns_view_dashboard"):
        st.switch_page("pages/Dashboard.py")
    

# Initialize session state
if 'selected_campaign' not in st.session_state:
    st.session_state.selected_campaign = None
if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = False
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'show_all_campaigns' not in st.session_state:
    st.session_state.show_all_campaigns = False
if 'show_manage' not in st.session_state:
    st.session_state.show_manage = False

# Debug: Check if coming from Create Campaign page
if st.session_state.selected_campaign and st.session_state.show_manage:
    st.info(f"📍 Navigated to manage Campaign ID: {st.session_state.selected_campaign}")


# Get campaigns from API with error handling
api = APIClient()

try:
    # Fetch campaigns - either paginated or all
    if st.session_state.show_all_campaigns:
        campaigns_response = api.get_all_campaigns()
    else:
        campaigns_response = api.get_campaigns(page=st.session_state.current_page)
    if not campaigns_response.get('success', True):  # Some APIs don't return success field
        st.error("Failed to load campaigns from server.")
        campaigns_response = {'results': [], 'count': 0}
except Exception as e:
    st.error(f"Connection error: {str(e)}")
    st.info("Please check your internet connection and try again.")
    campaigns_response = {'results': [], 'count': 0}

if campaigns_response.get('results'):
    campaigns = campaigns_response['results']
    
    # Create tab selection
    tab_options = ["📊 All Campaigns", "🎯 Manage Single Campaign"]
    
    # Determine which tab to show based on session state
    default_index = 1 if (st.session_state.show_manage and st.session_state.selected_campaign) else 0
    selected_tab = st.radio("Select View", tab_options, index=default_index, horizontal=True, key="tab_selector")
    
    if selected_tab == "📊 All Campaigns":
        st.session_state.show_manage = False
        # Campaign Overview Table
        st.markdown("### 📋 All Campaigns Overview")
        
        # Show total count and pagination info
        total_count = campaigns_response.get('count', len(campaigns))
        page_size = 20  # This matches Django's PAGE_SIZE setting
        total_pages = (total_count + page_size - 1) // page_size if not st.session_state.show_all_campaigns else 1
        
        col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
        with col1:
            st.caption(f"Total campaigns: {total_count}")
        with col2:
            if not st.session_state.show_all_campaigns:
                st.caption(f"Page {st.session_state.current_page} of {total_pages}")
            else:
                st.caption("Showing all campaigns")
        with col3:
            st.caption(f"Displaying: {len(campaigns)}")
        with col4:
            # Toggle between paginated and all campaigns
            show_all = st.checkbox("Show All", value=st.session_state.show_all_campaigns,
                                  help="Toggle between paginated view and showing all campaigns")
            if show_all != st.session_state.show_all_campaigns:
                st.session_state.show_all_campaigns = show_all
                st.session_state.current_page = 1  # Reset to first page when toggling
                st.rerun()
        
        # Create DataFrame for better display
        campaigns_df = pd.DataFrame(campaigns)
        
        if not campaigns_df.empty:
            # Add action column
            for idx, campaign in campaigns_df.iterrows():
                campaign_id = campaign['id']
                status = campaign['status']
                
                # Create action buttons based on status
                col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 2])
                
                with col1:
                    st.write(f"**{campaign['template_name']}**")
                    st.caption(f"ID: {campaign_id} | Created: {campaign.get('created_at', 'N/A')[:10]}")
                
                with col2:
                    status_color = STATUS_COLORS.get(status, '#999')
                    st.markdown(f"""
                    <span style="background-color: {status_color}; color: white; padding: 4px 8px; 
                                border-radius: 3px; font-size: 12px;">
                        {status.upper()}
                    </span>
                    """, unsafe_allow_html=True)
                
                with col3:
                    sent = campaign.get('sent_count', 0)
                    total = campaign.get('total_recipients', 0)
                    st.metric("Progress", f"{sent}/{total}")
                
                with col4:
                    if total > 0:
                        success_rate = (sent / total) * 100
                        st.metric("Rate", f"{success_rate:.1f}%")
                    else:
                        st.metric("Rate", "0%")
                
                with col5:
                    button_col1, button_col2 = st.columns(2)
                    with button_col1:
                        if st.button("Manage", key=f"manage_{campaign_id}"):
                            st.session_state.selected_campaign = campaign_id
                            st.session_state.show_manage = True
                            st.rerun()
                    
                    with button_col2:
                        # Export button - enabled for completed campaigns or campaigns with sent messages
                        has_data = campaign.get('sent_count', 0) > 0 or status == 'completed'
                        if st.button("📥 Export", 
                                    key=f"export_{campaign_id}",
                                    disabled=not has_data,
                                    help="Export report (available when messages have been sent)"):
                            # Generate report for this campaign
                            with st.spinner(f"Generating report for campaign {campaign_id}..."):
                                try:
                                    # Get campaign messages
                                    messages_response = api.get_campaign_messages(campaign_id)
                                    
                                    if messages_response.get('results'):
                                        messages_df = pd.DataFrame(messages_response['results'])
                                        
                                        # Add campaign info to the report
                                        report_data = {
                                            'Campaign ID': campaign_id,
                                            'Template': campaign['template_name'],
                                            'Status': status,
                                            'Total Recipients': campaign.get('total_recipients', 0),
                                            'Sent': campaign.get('sent_count', 0),
                                            'Delivered': campaign.get('delivered_count', 0),
                                            'Read': campaign.get('read_count', 0),
                                            'Failed': campaign.get('failed_count', 0),
                                            'Created At': campaign.get('created_at', ''),
                                            'Started At': campaign.get('started_at', ''),
                                            'Completed At': campaign.get('completed_at', '')
                                        }
                                        
                                        # Create Excel file
                                        output = io.BytesIO()
                                        
                                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                                            # Summary sheet
                                            summary_df = pd.DataFrame([report_data])
                                            summary_df.to_excel(writer, sheet_name='Summary', index=False)
                                            
                                            # Messages detail sheet
                                            if not messages_df.empty:
                                                # Select relevant columns
                                                export_columns = ['phone_number', 'status', 'sent_at', 
                                                                'delivered_at', 'read_at', 'failed_at', 
                                                                'error_message']
                                                available_cols = [col for col in export_columns if col in messages_df.columns]
                                                messages_export = messages_df[available_cols].copy()
                                                messages_export.to_excel(writer, sheet_name='Messages', index=False)
                                        
                                        # Generate download
                                        output.seek(0)
                                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        filename = f"campaign_{campaign_id}_report_{timestamp}.xlsx"
                                        
                                        st.download_button(
                                            label="📥 Download",
                                            data=output,
                                            file_name=filename,
                                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            key=f"download_{campaign_id}"
                                        )
                                        st.success(f"✅ Report ready: {filename}")
                                    else:
                                        st.warning("No message data available")
                                        
                                except Exception as e:
                                    st.error(f"Failed to generate report: {str(e)}")
                
                st.markdown("---")
        
        # Pagination controls (only show when not displaying all)
        if not st.session_state.show_all_campaigns:
            st.markdown("---")
            col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
            
            with col1:
                if st.button("⏮️ First", key="campaigns_first_page", 
                            disabled=st.session_state.current_page == 1):
                    st.session_state.current_page = 1
                    st.rerun()
            
            with col2:
                if st.button("◀️ Previous", key="campaigns_prev_page",
                            disabled=st.session_state.current_page == 1):
                    st.session_state.current_page -= 1
                    st.rerun()
            
            with col3:
                # Page number input
                new_page = st.number_input(
                    "Go to page",
                    min_value=1,
                    max_value=total_pages,
                    value=st.session_state.current_page,
                    step=1,
                    label_visibility="collapsed"
                )
                if new_page != st.session_state.current_page:
                    st.session_state.current_page = new_page
                    st.rerun()
            
            with col4:
                if st.button("▶️ Next", key="campaigns_next_page",
                            disabled=not campaigns_response.get('next')):
                    st.session_state.current_page += 1
                    st.rerun()
            
            with col5:
                if st.button("⏭️ Last", key="campaigns_last_page",
                            disabled=st.session_state.current_page == total_pages):
                    st.session_state.current_page = total_pages
                    st.rerun()
        
        # Refresh button
        st.markdown("---")
        if st.button("🔄 Refresh", key="campaigns_refresh"):
            st.rerun()
    
    elif selected_tab == "🎯 Manage Single Campaign":
        # Set the flag when this tab is selected
        st.session_state.show_manage = True
        
        # Campaign selector
        st.markdown("### 🎯 Select Campaign to Manage")
        
        col1, col2, col3 = st.columns([3, 1, 1])
        
        with col1:
            # Create campaign options
            campaign_options = {
                f"{c['id']} - {c['template_name']} ({c['status']})": c['id'] 
                for c in campaigns
            }
            
            # Find the index of the selected campaign if one is already selected
            selected_index = 0
            if st.session_state.selected_campaign:
                for idx, (option_text, campaign_id) in enumerate(campaign_options.items()):
                    if campaign_id == st.session_state.selected_campaign:
                        selected_index = idx
                        break
            
            selected_option = st.selectbox(
                "Choose a campaign",
                options=list(campaign_options.keys()),
                index=selected_index
            )
            
            if selected_option:
                st.session_state.selected_campaign = campaign_options[selected_option]
        
        with col2:
            auto_refresh = st.checkbox("Auto Refresh", value=st.session_state.auto_refresh)
            st.session_state.auto_refresh = auto_refresh
        
        with col3:
            if st.button("🔄 Refresh", key="campaigns_single_refresh"):
                st.rerun()
        
        # Auto refresh logic
        if st.session_state.auto_refresh:
            time.sleep(5)
            st.rerun()
        
        # Display selected campaign details
        if st.session_state.selected_campaign:
            campaign_id = st.session_state.selected_campaign
            
            # Get campaign details with error handling
            try:
                campaign_response = api.get_campaign(campaign_id)
                if not campaign_response.get('id'):
                    st.error("Failed to load campaign details.")
                    st.stop()
                campaign = campaign_response
            except Exception as e:
                st.error(f"Error loading campaign: {str(e)}")
                st.stop()
            
            try:
                stats_response = api.get_campaign_statistics(campaign_id)
                stats = stats_response.get('statistics', {}) if stats_response.get('success') else {}
            except Exception as e:
                st.warning(f"Could not load campaign statistics: {str(e)}")
                stats = {}
            
                st.markdown("---")
            
            # Campaign Header
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"## {campaign['template_name']}")
            with col2:
                status_color = STATUS_COLORS.get(campaign['status'], '#999')
                st.markdown(f"""
                <div style="background-color: {status_color}; color: white; padding: 8px; 
                            border-radius: 5px; text-align: center; font-weight: bold;">
                    {campaign['status'].upper()}
                </div>
                """, unsafe_allow_html=True)
            
            # Campaign Metrics
            st.markdown("### 📊 Campaign Metrics")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Total Recipients", campaign.get('total_recipients', 0))
            with col2:
                st.metric("Sent", campaign.get('sent_count', 0))
            with col3:
                st.metric("Delivered", campaign.get('delivered_count', 0))
            with col4:
                st.metric("Read", campaign.get('read_count', 0))
            with col5:
                st.metric("Failed", campaign.get('failed_count', 0))
        
            # Progress Bar
            if campaign['total_recipients'] > 0:
                progress = (campaign['sent_count'] / campaign['total_recipients']) * 100
                
                st.markdown("### 📈 Progress")
                progress_bar = st.progress(0)
                progress_bar.progress(int(progress))
                
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    st.markdown(f"""
                    <div style="text-align: center; font-size: 24px; font-weight: bold; color: {STATUS_COLORS.get('running')}"">
                        {progress:.1f}% Complete
                    </div>
                    """, unsafe_allow_html=True)
        
            # Campaign Actions
            st.markdown("---")
            st.markdown("### 🎮 Campaign Controls")
            
            # Check if campaign is stuck (running but all messages sent)
            is_stuck = (campaign['status'] == 'running' and 
                       campaign.get('sent_count', 0) == campaign.get('total_recipients', 0) and 
                       campaign.get('total_recipients', 0) > 0)
            
            if is_stuck:
                st.warning("⚠️ This campaign appears to be stuck in 'running' state even though all messages have been sent.")
            
            col1, col2, col3, col4, col5, col6 = st.columns(6)
            
            with col1:
                if campaign['status'] in ['pending', 'paused']:
                    if st.button("▶️ Start", key="campaigns_start_btn", type="primary"):
                        try:
                            response = api.start_campaign(campaign_id)
                            success = response.get('success', False)
                            message = response.get('message') if success else response.get('error', 'Unknown error')
                            
                            if success:
                                st.success(f"✅ {message}")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(f"❌ {message}")
                        except Exception as e:
                            st.error(f"❌ Failed to start campaign: {str(e)}")
            
            with col2:
                if campaign['status'] == 'running':
                    if st.button("⏸️ Pause", key="campaigns_pause_btn"):
                        try:
                            response = api.pause_campaign(campaign_id)
                            if response.get('success'):
                                st.success("Campaign paused!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(response.get('error', 'Failed to pause campaign'))
                        except Exception as e:
                            st.error(f"❌ Failed to pause campaign: {str(e)}")
            
            with col3:
                if campaign['status'] == 'paused':
                    if st.button("▶️ Resume", key="campaigns_resume_btn"):
                        try:
                            response = api.resume_campaign(campaign_id)
                            if response.get('success'):
                                st.success("Campaign resumed!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(response.get('error', 'Failed to resume campaign'))
                        except Exception as e:
                            st.error(f"❌ Failed to resume campaign: {str(e)}")
            
            with col4:
                if st.button("📊 Refresh Stats", key="campaigns_refresh_stats"):
                    st.rerun()
            
            with col5:
                # Check Campaign Status button for stuck campaigns
                if is_stuck or campaign['status'] == 'running':
                    if st.button("🔍 Check Status", key="campaigns_check_status", 
                                help="Check and update campaign completion status"):
                        with st.spinner("Checking campaign status..."):
                            try:
                                response = api.check_campaign_status(campaign_id)
                                if response.get('success'):
                                    if response.get('updated'):
                                        st.success("✅ Campaign status updated to completed!")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        pending = response.get('pending_messages', 0)
                                        if pending > 0:
                                            st.info(f"Campaign still has {pending} pending messages")
                                        else:
                                            st.info(f"Campaign status: {response.get('message', 'Status checked')}")
                                else:
                                    st.error(f"Failed: {response.get('error', response.get('detail', 'Check backend server'))}")
                            except Exception as e:
                                st.error(f"Error: {str(e)}. Make sure the Django server is running.")
            
            with col6:
                # Export Report button - enabled when campaign has data to export
                # Enable for completed campaigns or campaigns with sent messages
                has_data = campaign.get('sent_count', 0) > 0 or campaign['status'] == 'completed'
                
                if st.button("📥 Export Report", key="campaigns_export_report", 
                            disabled=not has_data,
                            help="Export campaign report (available when messages have been sent)"):
                    # Generate campaign report
                    with st.spinner("Generating report..."):
                        try:
                            # Get campaign messages
                            messages_response = api.get_campaign_messages(campaign_id)
                            
                            if messages_response.get('results'):
                                messages_df = pd.DataFrame(messages_response['results'])
                                
                                # Add campaign info to the report
                                report_data = {
                                    'Campaign ID': campaign_id,
                                    'Template': campaign['template_name'],
                                    'Status': campaign['status'],
                                    'Total Recipients': campaign.get('total_recipients', 0),
                                    'Sent': campaign.get('sent_count', 0),
                                    'Delivered': campaign.get('delivered_count', 0),
                                    'Read': campaign.get('read_count', 0),
                                    'Failed': campaign.get('failed_count', 0),
                                    'Success Rate': f"{campaign.get('success_rate', 0):.2f}%",
                                    'Created At': campaign.get('created_at', ''),
                                    'Started At': campaign.get('started_at', ''),
                                    'Completed At': campaign.get('completed_at', '')
                                }
                                
                                # Create Excel file with multiple sheets
                                output = io.BytesIO()
                                
                                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                                    # Summary sheet
                                    summary_df = pd.DataFrame([report_data])
                                    summary_df.to_excel(writer, sheet_name='Summary', index=False)
                                    
                                    # Messages detail sheet
                                    if not messages_df.empty:
                                        # Select relevant columns
                                        export_columns = ['phone_number', 'status', 'sent_at', 
                                                        'delivered_at', 'read_at', 'failed_at', 
                                                        'error_message']
                                        available_cols = [col for col in export_columns if col in messages_df.columns]
                                        messages_export = messages_df[available_cols].copy()
                                        messages_export.to_excel(writer, sheet_name='Messages', index=False)
                                
                                # Generate download
                                output.seek(0)
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                filename = f"campaign_{campaign_id}_report_{timestamp}.xlsx"
                                
                                st.download_button(
                                    label="📥 Download Report",
                                    data=output,
                                    file_name=filename,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                )
                                st.success(f"✅ Report ready for download: {filename}")
                            else:
                                st.warning("No message data available for this campaign")
                                
                        except Exception as e:
                            st.error(f"Failed to generate report: {str(e)}")
            
            
            # Simplified Statistics (more minimal)
            if campaign['status'] in ['completed', 'running', 'paused']:
                st.markdown("---")
                st.markdown("### 📊 Campaign Analytics")
                
                # Simple metrics in a clean layout
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    sent_pct = (campaign['sent_count'] / campaign['total_recipients'] * 100) if campaign['total_recipients'] > 0 else 0
                    st.metric("Sent Rate", f"{sent_pct:.1f}%", f"{campaign['sent_count']}/{campaign['total_recipients']}")
                
                with col2:
                    delivered_pct = (campaign['delivered_count'] / campaign['sent_count'] * 100) if campaign['sent_count'] > 0 else 0
                    st.metric("Delivery Rate", f"{delivered_pct:.1f}%", f"{campaign['delivered_count']} delivered")
                
                with col3:
                    read_pct = (campaign['read_count'] / campaign['delivered_count'] * 100) if campaign['delivered_count'] > 0 else 0
                    st.metric("Read Rate", f"{read_pct:.1f}%", f"{campaign['read_count']} read")
                
                with col4:
                    failed_pct = (campaign['failed_count'] / campaign['total_recipients'] * 100) if campaign['total_recipients'] > 0 else 0
                    st.metric("Failed Rate", f"{failed_pct:.1f}%", f"{campaign['failed_count']} failed", delta_color="inverse")
                
                # Simple progress visualization
                if campaign['total_recipients'] > 0:
                    st.markdown("#### Message Flow")
                    
                    # Display as simple progress bars
                    stages = ['Sent', 'Delivered', 'Read']
                    counts = [
                        campaign['sent_count'],
                        campaign['delivered_count'],
                        campaign['read_count']
                    ]
                    colors = ['#2196F3', '#4CAF50', '#00BCD4']
                    
                    for stage, count, color in zip(stages, counts, colors):
                        pct = (count / campaign['total_recipients']) * 100
                        col1, col2, col3 = st.columns([1, 3, 1])
                        with col1:
                            st.caption(stage)
                        with col2:
                            st.progress(pct / 100)
                        with col3:
                            st.caption(f"{count} ({pct:.1f}%)")
            
            # Campaign Timeline
            if campaign.get('started_at'):
                st.markdown("---")
                st.markdown("### ⏱️ Campaign Timeline")
                
                timeline_data = []
                
                if campaign.get('created_at'):
                    timeline_data.append({
                        'Event': 'Created',
                        'Time': campaign['created_at'],
                        'Icon': '🆕'
                    })
                
                if campaign.get('started_at'):
                    timeline_data.append({
                        'Event': 'Started',
                        'Time': campaign['started_at'],
                        'Icon': '▶️'
                    })
                
                if campaign.get('completed_at'):
                    timeline_data.append({
                        'Event': 'Completed',
                        'Time': campaign['completed_at'],
                        'Icon': '✅'
                    })
                
                for item in timeline_data:
                    col1, col2 = st.columns([1, 5])
                    with col1:
                        st.markdown(f"### {item['Icon']}")
                    with col2:
                        st.markdown(f"**{item['Event']}**  \n{item['Time']}")
            
            # Messages Preview (Optional)
            with st.expander("📨 View Messages (Sample)", expanded=False):
                messages_response = api.get_campaign_messages(campaign_id)
                if messages_response.get('results'):
                    messages_df = pd.DataFrame(messages_response['results'][:10])
                    
                    if not messages_df.empty:
                        display_columns = ['phone_number', 'status', 'sent_at', 'delivered_at']
                        available_columns = [col for col in display_columns if col in messages_df.columns]
                        
                        if available_columns:
                            st.dataframe(
                                messages_df[available_columns],
                                hide_index=True
                            )
                        else:
                            st.info("No message details available")
                else:
                    st.info("No messages found")
            
else:
    st.info("No campaigns found. Create your first campaign to get started!")
    if st.button("➕ Create Your First Campaign", key="campaigns_create_first"):
        st.switch_page("pages/Create_Campaign.py")

# Add workflow explanation at the bottom
st.markdown("---")
with st.expander("📚 Campaign Workflow Guide", expanded=False):
    st.markdown("""
    ### Campaign Status Flow:
    
    1. **📝 Draft** → Created but file still processing
    2. **✅ Pending** → File processed, ready to start
    3. **🚀 Running** → Actively sending messages
    4. **⏸️ Paused** → Temporarily stopped (can resume)
    5. **✅ Completed** → All messages sent
    6. **❌ Failed** → Error occurred
    
    ### How to Start a Campaign:
    
    1. **Create Campaign** → Upload file with contacts
    2. **Wait for Processing** → File is validated and messages created (usually 5-30 seconds)
    3. **Check Status** → Refresh to see if status changed from 'draft' to 'pending'
    4. **Start Campaign** → Click "Start Campaign" button when status is 'pending'
    5. **Monitor Progress** → Watch the progress bar and metrics update
    
    ### Troubleshooting:
    
    - **Campaign stuck in 'draft'?** → Make sure Celery worker is running
    - **Can't start campaign?** → Check if status is 'pending' and file has valid recipients
    - **No progress after starting?** → Check WhatsApp API credentials in backend
    - **High failure rate?** → Verify phone numbers format and template name
    
    ### Debug Mode:
    
    - **Enable Debug Info** → Check the "Show Debug Info" box in the sidebar
    - **Test API Connection** → Use the "Test API Connection" button
    - **View Raw Data** → Expand debug sections to see API responses
    - **Detailed Start Process** → Debug mode shows step-by-step start campaign process
    """)
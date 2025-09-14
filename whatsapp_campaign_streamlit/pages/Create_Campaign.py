# streamlit-app/pages/2_➕_Create_Campaign.py

import streamlit as st
import pandas as pd
import io
from components.auth import require_auth, logout
from components.api_client import APIClient

# Check authentication
require_auth()

# Page header
st.title("➕ Create New Campaign")

# Add logout button in sidebar
with st.sidebar:
    if st.button("🚪 Logout", key="create_logout"):
        logout()
    
    # Show navigation hint if campaign was just created
    if st.session_state.get('campaign_created', False) and st.session_state.get('selected_campaign'):
        st.markdown("---")
        st.success(f"✅ Campaign {st.session_state.selected_campaign} created!")
        if st.button("📈 Go to Campaigns Page", key="create_goto_campaigns", type="primary"):
            # Clear the flag
            st.session_state.campaign_created = False
            # Note: We can't navigate directly, but the button press will be visible
            st.info("Please click on 'Campaigns' in the sidebar menu")
    
    st.markdown("---")
    st.markdown("### 📝 File Format")
    st.markdown("""
    Your CSV/Excel file must have these columns:
    - **phone**: Phone number with country code
    - **has_variables**: true/false
    - **variables**: JSON array of variables
    - **has_media**: true/false
    - **media_url**: URL of media file
    """)
    
    # Download sample file
    sample_data = pd.DataFrame({
        'phone': ['+919876543210', '+919876543211'],
        'has_variables': [True, False],
        'variables': ['["John", "DISCOUNT2024"]', ''],
        'has_media': [False, True],
        'media_url': ['', 'https://example.com/image.jpg']
    })
    
    csv = sample_data.to_csv(index=False)
    st.download_button(
        label="📥 Download Sample CSV",
        data=csv,
        file_name="sample_campaign.csv",
        mime="text/csv",
        width="stretch"
    )

# Initialize session state
if 'file_validated' not in st.session_state:
    st.session_state.file_validated = False
if 'file_data' not in st.session_state:
    st.session_state.file_data = None
if 'validation_response' not in st.session_state:
    st.session_state.validation_response = None
if 'file_content' not in st.session_state:
    st.session_state.file_content = None
if 'file_name' not in st.session_state:
    st.session_state.file_name = None

# Campaign creation form
st.markdown("### 📋 Campaign Details")

# Step 1: Template Name
template_name = st.text_input(
    "Template Name *",
    placeholder="Enter your WhatsApp template name",
    help="This should match the approved template name in 360dialog"
)

st.markdown("---")

# Step 2: File Upload
st.markdown("### 📁 Upload Recipients File")

uploaded_file = st.file_uploader(
    "Choose a CSV or Excel file",
    type=['csv', 'xlsx', 'xls'],
    help="Upload your contact list with the required columns"
)

# File validation
if uploaded_file is not None:
    # Store file content in session state when first uploaded
    if st.session_state.file_name != uploaded_file.name:
        # Read the file content into bytes
        file_bytes = uploaded_file.read()
        st.session_state.file_content = file_bytes
        st.session_state.file_name = uploaded_file.name
        st.session_state.file_validated = False  # Reset validation when new file is uploaded
        
        # Reset file pointer for display
        uploaded_file.seek(0)
    
    # Show file info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("File Name", uploaded_file.name)
    with col2:
        file_size = len(st.session_state.file_content) / 1024  # Convert to KB
        st.metric("File Size", f"{file_size:.2f} KB")
    with col3:
        file_type = uploaded_file.name.split('.')[-1].upper()
        st.metric("File Type", file_type)
    
    # Validate button
    if st.button("🔍 Validate File", key="create_validate_file"):
        with st.spinner("Validating file..."):
            # Create a file-like object from stored content
            file_to_send = io.BytesIO(st.session_state.file_content)
            file_to_send.name = st.session_state.file_name
            
            # Determine MIME type
            if uploaded_file.name.endswith('.csv'):
                file_to_send.type = 'text/csv'
            else:
                file_to_send.type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            
            api = APIClient()
            try:
                response = api.validate_file(file_to_send)
                
                if response.get('success'):
                    st.session_state.file_validated = True
                    st.session_state.file_data = response.get('file_info', {})
                    st.session_state.validation_response = response
                    st.success("✅ File validated successfully!")
                else:
                    st.error(f"❌ Validation failed: {response.get('error', 'Unknown error')}")
                    st.session_state.file_validated = False
                    st.session_state.validation_response = None
            except Exception as e:
                st.error(f"❌ Connection error during validation: {str(e)}")
                st.session_state.file_validated = False
                st.session_state.validation_response = None
    
    # Show validation results
    if st.session_state.file_validated and st.session_state.file_data:
        st.markdown("---")
        st.markdown("### ✅ Validation Results")
        
        file_info = st.session_state.file_data
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Rows", file_info.get('total_rows', 0))
        with col2:
            st.metric("Valid Rows", file_info.get('valid_rows', 0), 
                     delta=None if file_info.get('valid_rows', 0) == file_info.get('total_rows', 0) else f"-{file_info.get('invalid_rows', 0)}")
        with col3:
            success_rate = (file_info.get('valid_rows', 0) / file_info.get('total_rows', 1)) * 100
            st.metric("Success Rate", f"{success_rate:.1f}%")
        
        # Show validation errors if any
        validation_response = st.session_state.get('validation_response', {})
        if validation_response and 'validation_errors' in validation_response and validation_response['validation_errors']:
            with st.expander("⚠️ View Validation Errors", expanded=False):
                errors_df = pd.DataFrame(validation_response['validation_errors'])
                st.dataframe(errors_df, width="stretch", hide_index=True)
        
        # Preview data
        if st.session_state.file_content:
            try:
                # Create file-like object from stored content for preview
                file_for_preview = io.BytesIO(st.session_state.file_content)
                
                # Read based on file type
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(file_for_preview)
                else:
                    df = pd.read_excel(file_for_preview)
                
                with st.expander("👁️ Preview Data (First 5 rows)", expanded=True):
                    st.dataframe(df.head(), width="stretch", hide_index=True)
                    
                # Show data statistics
                col1, col2 = st.columns(2)
                with col1:
                    st.info(f"📊 **Data Shape**: {df.shape[0]} rows × {df.shape[1]} columns")
                with col2:
                    st.info(f"📋 **Columns**: {', '.join(df.columns)}")
                    
            except Exception as e:
                st.warning(f"Could not preview file: {str(e)}")

st.markdown("---")

# Create Campaign Button
col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    create_button = st.button(
        "🚀 Create Campaign", 
        key="create_campaign_main_btn",
        use_container_width=False, 
        type="primary",
        disabled=not (template_name and uploaded_file and st.session_state.file_validated)
    )

if create_button:
    with st.spinner("Creating campaign..."):
        # Create a fresh file-like object from stored content
        file_to_upload = io.BytesIO(st.session_state.file_content)
        file_to_upload.name = st.session_state.file_name
        
        # Set MIME type
        if st.session_state.file_name.endswith('.csv'):
            file_to_upload.type = 'text/csv'
        else:
            file_to_upload.type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        
        api = APIClient()
        try:
            response = api.create_campaign(template_name, file_to_upload)
            
            if response.get('success'):
                st.success("✅ Campaign created successfully!")
                st.balloons()
                
                # Clear session state immediately after success
                st.session_state.file_validated = False
                st.session_state.file_data = None
                st.session_state.validation_response = None
                st.session_state.file_content = None
                st.session_state.file_name = None
                
                # Show campaign details
                campaign = response.get('campaign', {})
                
                # Store campaign ID in session state
                st.session_state.selected_campaign = campaign.get('id')
                st.session_state.show_manage = True
                st.session_state.campaign_created = True
                
                st.markdown("---")
                st.markdown("### 🎉 Campaign Created Successfully!")
                
                # Display campaign info
                col1, col2 = st.columns(2)
                with col1:
                    st.info(f"""
                    **Campaign ID:** {campaign.get('id')}  
                    **Template:** {campaign.get('template_name')}  
                    **Status:** {campaign.get('status')}  
                    """)
                with col2:
                    st.info(f"""
                    **Recipients:** {campaign.get('total_recipients', 0)}  
                    **Created:** {campaign.get('created_at', 'N/A')[:19] if campaign.get('created_at') else 'N/A'}  
                    """)
                
                st.markdown("---")
                
                # Add prominent navigation message
                st.success("✅ Campaign created successfully! Navigate to **📈 Campaigns** page from the sidebar to manage your campaign.")
                
                # Add button to create another campaign
                if st.button("➕ Create Another Campaign", key="create_another_campaign"):
                    # Clear session state and refresh
                    st.session_state.selected_campaign = None
                    st.session_state.show_manage = False
                    st.session_state.campaign_created = False
                    st.rerun()
                
                # Info message
                st.info("💡 Tip: Go to 'Manage Campaigns' to start, pause, or monitor your campaign.")
                
            else:
                st.error(f"❌ Failed to create campaign: {response.get('error', 'Unknown error')}")
                
        except Exception as e:
            st.error(f"❌ Connection error during campaign creation: {str(e)}")

# Instructions
st.markdown("---")
st.info("""
**📌 Instructions:**
1. Enter the exact template name as approved in 360dialog
2. Upload a CSV or Excel file with your contact list
3. Validate the file to check for errors
4. Create the campaign once validation is successful
5. You can start the campaign immediately or manage it later
""")

# Tips
with st.expander("💡 Tips for Success", expanded=False):
    st.markdown("""
    - **Phone Numbers**: Always include country code (e.g., +91 for India)
    - **Variables**: Use JSON format for multiple variables: `["Name", "Code"]`
    - **Media URLs**: Ensure URLs are publicly accessible
    - **Template Name**: Must exactly match your approved WhatsApp template
    - **File Size**: Keep files under 10MB for optimal performance
    - **Testing**: Start with a small batch to test your template
    """)

# File format example
with st.expander("📄 File Format Example", expanded=False):
    st.markdown("### Example CSV Content:")
    example_df = pd.DataFrame({
        'phone': ['+919876543210', '+919876543211', '+919876543212'],
        'has_variables': [True, True, False],
        'variables': ['["John Doe", "SUMMER2024"]', '["Jane Smith", "WELCOME50"]', ''],
        'has_media': [False, True, False],
        'media_url': ['', 'https://example.com/welcome.jpg', '']
    })
    st.dataframe(example_df, width="stretch", hide_index=True)
    

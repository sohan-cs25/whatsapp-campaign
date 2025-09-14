# test_whatsapp_system.py
# Test script to verify WhatsApp integration step by step

import os
import sys
import django
import time

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from campaigns.models import Campaign, UploadedFile, Message
from campaigns.whatsapp_360_client import WhatsApp360Client
from campaigns.tasks import process_uploaded_file, start_campaign_task, send_whatsapp_message
from django.contrib.auth.models import User
import pandas as pd
from django.core.files.base import ContentFile
from io import BytesIO

def test_360dialog_client():
    """Test 1: Verify 360dialog client configuration"""
    print("\n" + "="*50)
    print("TEST 1: 360dialog Client Configuration")
    print("="*50)
    
    try:
        from decouple import config
        api_key = config('WHATSAPP_360_API_KEY', default='')
        
        if not api_key:
            print("❌ WHATSAPP_360_API_KEY not configured in .env")
            print("Please add: WHATSAPP_360_API_KEY=your-api-key")
            return False
        
        print(f"✅ API Key configured: ***{api_key[-4:]}")
        
        # Test client initialization
        client = WhatsApp360Client()
        print("✅ WhatsApp client initialized successfully")
        
        # Test template component building
        components = client.build_template_components(
            body_params=["John", "TEST123"]
        )
        print(f"✅ Template components built: {components}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_send_template_manual():
    """Test 2: Send a test template message directly"""
    print("\n" + "="*50)
    print("TEST 2: Send Test Template Message")
    print("="*50)
    
    # Get test phone number
    test_phone = input("Enter test phone number (with country code, e.g., +919876543210): ")
    template_name = input("Enter your approved template name: ")
    
    if not test_phone or not template_name:
        print("❌ Phone number and template name are required")
        return False
    
    try:
        client = WhatsApp360Client()
        
        print(f"\nSending test message to {test_phone}...")
        result = client.send_template_message(
            phone_number=test_phone,
            template_name=template_name,
            language_code='en'
        )
        
        if result['success']:
            print(f"✅ Message sent successfully!")
            print(f"   Message ID: {result['message_id']}")
            print(f"   Response: {result.get('response')}")
            return True
        else:
            print(f"❌ Failed to send message")
            print(f"   Error: {result.get('error')}")
            print(f"   Status Code: {result.get('status_code')}")
            print(f"   Full Response: {result}")
            return False
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_file_processing():
    """Test 3: Test file processing"""
    print("\n" + "="*50)
    print("TEST 3: File Processing")
    print("="*50)
    
    try:
        # Get or create test user
        user = User.objects.first()
        if not user:
            print("❌ No users found. Please create a user first.")
            return False
        
        print(f"✅ Using user: {user.username}")
        
        # Create test campaign
        campaign = Campaign.objects.create(
            user=user,
            template_name="test_template",
            status='draft'
        )
        print(f"✅ Created test campaign: {campaign.id}")
        
        # Create test CSV data
        test_data = pd.DataFrame({
            'phone': ['+919876543210', '+919876543211'],
            'has_variables': [True, False],
            'variables': ['["Test User", "CODE123"]', ''],
            'has_media': [False, False],
            'media_url': ['', '']
        })
        
        # Save to BytesIO
        csv_buffer = BytesIO()
        test_data.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)
        
        # Create uploaded file
        uploaded_file = UploadedFile.objects.create(
            user=user,
            campaign=campaign,
            file_name='test.csv',
            file_type='csv',
            status='pending'
        )
        
        # Save the file
        uploaded_file.file_path.save('test.csv', ContentFile(csv_buffer.getvalue()))
        print(f"✅ Created uploaded file: {uploaded_file.id}")
        
        # Process file synchronously for testing
        print("\nProcessing file...")
        result = process_uploaded_file(uploaded_file.id)
        
        print(f"✅ File processed: {result}")
        
        # Check results
        uploaded_file.refresh_from_db()
        campaign.refresh_from_db()
        
        print(f"\nFile Status: {uploaded_file.status}")
        print(f"Valid Rows: {uploaded_file.valid_rows}")
        print(f"Invalid Rows: {uploaded_file.invalid_rows}")
        print(f"Campaign Status: {campaign.status}")
        print(f"Total Recipients: {campaign.total_recipients}")
        
        # Check messages created
        messages = Message.objects.filter(campaign=campaign)
        print(f"Messages Created: {messages.count()}")
        
        for msg in messages:
            print(f"  - {msg.phone_number}: {msg.status}")
        
        # Cleanup
        campaign.delete()
        
        return messages.count() > 0
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_campaign_flow():
    """Test 4: Complete campaign flow"""
    print("\n" + "="*50)
    print("TEST 4: Complete Campaign Flow")
    print("="*50)
    
    try:
        # Get last campaign
        campaign = Campaign.objects.filter(status='pending').last()
        if not campaign:
            print("❌ No pending campaigns found. Run Test 3 first.")
            return False
        
        print(f"✅ Found campaign: {campaign.id} - {campaign.template_name}")
        
        # Check messages
        messages = Message.objects.filter(campaign=campaign)
        print(f"Messages in campaign: {messages.count()}")
        
        if messages.count() == 0:
            print("❌ No messages found for campaign")
            return False
        
        # Test sending first message
        first_message = messages.first()
        print(f"\nTesting message send for: {first_message.phone_number}")
        
        # Send message synchronously for testing
        send_whatsapp_message(first_message.id)
        
        # Check status
        first_message.refresh_from_db()
        print(f"Message Status: {first_message.status}")
        print(f"Message ID: {first_message.message_id}")
        print(f"Error: {first_message.error_message}")
        
        return first_message.status == 'sent'
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_file_processing_issue():
    """Debug why files have 0 rows"""
    print("\n" + "="*50)
    print("DEBUG: File Processing Issue")
    print("="*50)
    
    # Get recent uploaded files
    recent_files = UploadedFile.objects.order_by('-id')[:5]
    
    for uf in recent_files:
        print(f"\nFile ID: {uf.id}")
        print(f"  Name: {uf.file_name}")
        print(f"  Status: {uf.status}")
        print(f"  Row Count: {uf.row_count}")
        print(f"  Valid Rows: {uf.valid_rows}")
        print(f"  File Path Exists: {uf.file_path and os.path.exists(uf.file_path.path)}")
        
        if uf.file_path and os.path.exists(uf.file_path.path):
            try:
                # Try to read the file
                if uf.file_type == 'csv':
                    df = pd.read_csv(uf.file_path.path)
                else:
                    df = pd.read_excel(uf.file_path.path)
                
                print(f"  Actual Rows in File: {len(df)}")
                print(f"  Columns: {list(df.columns)}")
                if len(df) > 0:
                    print(f"  First Row: {df.iloc[0].to_dict()}")
            except Exception as e:
                print(f"  Error reading file: {e}")
        
        if uf.error_log:
            print(f"  Error Log: {uf.error_log}")

def main():
    """Run all tests"""
    print("\n" + "#"*50)
    print("# WhatsApp Campaign System Test")
    print("#"*50)
    
    # Test 1: Check configuration
    if not test_360dialog_client():
        print("\n⚠️ Fix configuration issues before proceeding")
        return
    
    # Check file processing issue
    check_file_processing_issue()
    
    # Ask user what to test
    print("\n" + "="*50)
    print("Choose what to test:")
    print("1. Send test WhatsApp message")
    print("2. Test file processing")
    print("3. Test complete campaign flow")
    print("4. Debug file processing issues")
    print("5. Run all tests")
    
    choice = input("\nEnter choice (1-5): ")
    
    if choice == '1':
        test_send_template_manual()
    elif choice == '2':
        test_file_processing()
    elif choice == '3':
        test_campaign_flow()
    elif choice == '4':
        check_file_processing_issue()
    elif choice == '5':
        test_send_template_manual()
        test_file_processing()
        test_campaign_flow()

if __name__ == "__main__":
    main()
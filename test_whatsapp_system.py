# test_system.py
# Save this in your Django project root (same folder as manage.py)
# Run with: python test_system.py

import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from campaigns.models import Campaign, UploadedFile, Message
from campaigns.whatsapp_360_client import WhatsApp360Client
from django.contrib.auth.models import User
from decouple import config
import pandas as pd

def check_configuration():
    """Check if system is configured properly"""
    print("\n" + "="*50)
    print("CONFIGURATION CHECK")
    print("="*50)
    
    # Check API key
    api_key = config('WHATSAPP_360_API_KEY', default='')
    if api_key:
        print(f"✅ API Key configured: ***{api_key[-4:]}")
    else:
        print("❌ WHATSAPP_360_API_KEY not found in .env")
    
    # Check database
    try:
        user_count = User.objects.count()
        print(f"✅ Database connected - {user_count} users found")
    except Exception as e:
        print(f"❌ Database error: {e}")
    
    # Check file upload directory
    from django.conf import settings
    media_root = settings.MEDIA_ROOT
    if os.path.exists(media_root):
        print(f"✅ Media directory exists: {media_root}")
    else:
        print(f"❌ Media directory not found: {media_root}")
        os.makedirs(media_root, exist_ok=True)
        print("   Created media directory")

def check_recent_data():
    """Check recent campaigns and files"""
    print("\n" + "="*50)
    print("RECENT DATA CHECK")
    print("="*50)
    
    # Check uploaded files
    print("\n📁 Recent Uploaded Files:")
    files = UploadedFile.objects.order_by('-id')[:5]
    if not files:
        print("   No files found")
    for f in files:
        print(f"   File {f.id}: {f.file_name}")
        print(f"      Status: {f.status}")
        print(f"      Rows: {f.row_count}, Valid: {f.valid_rows}, Invalid: {f.invalid_rows}")
        print(f"      File exists: {f.file_path and os.path.exists(f.file_path.path)}")
        if f.error_log:
            print(f"      Error: {f.error_log}")
    
    # Check campaigns
    print("\n📊 Recent Campaigns:")
    campaigns = Campaign.objects.order_by('-id')[:5]
    if not campaigns:
        print("   No campaigns found")
    for c in campaigns:
        print(f"   Campaign {c.id}: {c.template_name}")
        print(f"      Status: {c.status}")
        print(f"      Recipients: {c.total_recipients}")
        print(f"      Sent: {c.sent_count}, Delivered: {c.delivered_count}")
    
    # Check messages
    print("\n💬 Messages Statistics:")
    total_messages = Message.objects.count()
    print(f"   Total messages: {total_messages}")
    if total_messages > 0:
        status_counts = {}
        for status in ['queued', 'sent', 'delivered', 'failed']:
            count = Message.objects.filter(status=status).count()
            status_counts[status] = count
        print(f"   Status breakdown: {status_counts}")

def test_file_reading():
    """Test reading uploaded files directly"""
    print("\n" + "="*50)
    print("FILE READING TEST")
    print("="*50)
    
    # Get most recent file
    latest_file = UploadedFile.objects.order_by('-id').first()
    if not latest_file:
        print("No files to test")
        return
    
    print(f"Testing file: {latest_file.file_name}")
    print(f"File path: {latest_file.file_path.path if latest_file.file_path else 'None'}")
    
    if latest_file.file_path:
        try:
            file_path = latest_file.file_path.path
            print(f"Full path: {file_path}")
            print(f"File exists: {os.path.exists(file_path)}")
            
            if os.path.exists(file_path):
                # Get file size
                file_size = os.path.getsize(file_path)
                print(f"File size: {file_size} bytes")
                
                # Try to read the file
                if latest_file.file_type == 'csv':
                    df = pd.read_csv(file_path)
                else:
                    df = pd.read_excel(file_path)
                
                print(f"✅ Successfully read file!")
                print(f"   Shape: {df.shape}")
                print(f"   Columns: {list(df.columns)}")
                print("\nFirst 2 rows:")
                print(df.head(2))
                
                # Check required columns
                required = ['phone', 'has_variables', 'variables', 'has_media', 'media_url']
                missing = [col for col in required if col not in df.columns]
                if missing:
                    print(f"⚠️  Missing columns: {missing}")
                else:
                    print("✅ All required columns present")
                    
        except Exception as e:
            print(f"❌ Error reading file: {e}")
            import traceback
            traceback.print_exc()

def test_send_message():
    """Test sending a WhatsApp message"""
    print("\n" + "="*50)
    print("WHATSAPP API TEST")
    print("="*50)
    
    api_key = config('WHATSAPP_360_API_KEY', default='')
    if not api_key:
        print("❌ API key not configured. Skipping test.")
        return
    
    choice = input("\nDo you want to test sending a WhatsApp message? (y/n): ")
    if choice.lower() != 'y':
        print("Skipping WhatsApp test")
        return
    
    phone = input("Enter test phone number (e.g., +919876543210): ")
    template = input("Enter template name: ")
    
    if not phone or not template:
        print("Phone and template required")
        return
    
    try:
        client = WhatsApp360Client()
        print(f"\nSending to {phone} with template '{template}'...")
        
        result = client.send_template_message(
            phone_number=phone,
            template_name=template,
            language_code='en'
        )
        
        if result['success']:
            print("✅ Message sent successfully!")
            print(f"   Message ID: {result['message_id']}")
        else:
            print("❌ Failed to send message")
            print(f"   Error: {result.get('error')}")
            print(f"   Full response: {result}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()

def test_manual_file_process():
    """Manually process the latest file"""
    print("\n" + "="*50)
    print("MANUAL FILE PROCESSING TEST")
    print("="*50)
    
    latest_file = UploadedFile.objects.filter(status='pending').order_by('-id').first()
    if not latest_file:
        latest_file = UploadedFile.objects.order_by('-id').first()
    
    if not latest_file:
        print("No files to process")
        return
    
    print(f"File to process: {latest_file.file_name} (ID: {latest_file.id})")
    print(f"Current status: {latest_file.status}")
    
    choice = input("\nProcess this file? (y/n): ")
    if choice.lower() != 'y':
        return
    
    from campaigns.tasks import process_uploaded_file
    
    try:
        print("Processing file...")
        result = process_uploaded_file(latest_file.id)
        print(f"✅ Result: {result}")
        
        # Check updated status
        latest_file.refresh_from_db()
        print(f"\nUpdated status: {latest_file.status}")
        print(f"Rows processed: {latest_file.row_count}")
        print(f"Valid: {latest_file.valid_rows}, Invalid: {latest_file.invalid_rows}")
        
        # Check messages created
        if latest_file.campaign:
            messages = Message.objects.filter(campaign=latest_file.campaign)
            print(f"Messages created: {messages.count()}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("\n" + "#"*50)
    print("# WHATSAPP CAMPAIGN SYSTEM DIAGNOSTICS")
    print("#"*50)
    
    # Run all checks
    check_configuration()
    check_recent_data()
    test_file_reading()
    
    print("\n" + "="*50)
    print("ADDITIONAL TESTS")
    print("="*50)
    print("1. Test WhatsApp message sending")
    print("2. Manually process a file")
    print("3. Exit")
    
    choice = input("\nSelect option (1-3): ")
    
    if choice == '1':
        test_send_message()
    elif choice == '2':
        test_manual_file_process()

if __name__ == "__main__":
    main()
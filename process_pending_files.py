# process_pending_files.py
# Save in Django project root and run: python process_pending_files.py

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from campaigns.models import UploadedFile, Campaign, Message
from campaigns.tasks import process_uploaded_file

def process_all_pending_files():
    """Process all pending uploaded files"""
    
    # Get all pending files
    pending_files = UploadedFile.objects.filter(status='pending')
    
    print(f"Found {pending_files.count()} pending files")
    
    for file in pending_files:
        print(f"\nProcessing file {file.id}: {file.file_name}")
        print(f"  Campaign: {file.campaign.template_name if file.campaign else 'None'}")
        
        try:
            # Process the file
            result = process_uploaded_file(file.id)
            print(f"  ✅ Processed successfully: {result}")
            
            # Check results
            file.refresh_from_db()
            if file.campaign:
                file.campaign.refresh_from_db()
                messages = Message.objects.filter(campaign=file.campaign).count()
                print(f"  Status: {file.status}")
                print(f"  Rows: {file.row_count}, Valid: {file.valid_rows}")
                print(f"  Campaign status: {file.campaign.status}")
                print(f"  Messages created: {messages}")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")

def check_campaigns_ready_to_start():
    """Check which campaigns are ready to start"""
    
    print("\n" + "="*50)
    print("Campaigns Ready to Start:")
    print("="*50)
    
    pending_campaigns = Campaign.objects.filter(status='pending')
    
    for campaign in pending_campaigns:
        messages = Message.objects.filter(campaign=campaign).count()
        print(f"\nCampaign {campaign.id}: {campaign.template_name}")
        print(f"  Recipients: {campaign.total_recipients}")
        print(f"  Messages: {messages}")
        print(f"  Ready: {'Yes' if messages > 0 else 'No'}")

if __name__ == "__main__":
    process_all_pending_files()
    check_campaigns_ready_to_start()
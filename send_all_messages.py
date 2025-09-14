# send_all_messages.py
# Save in Django root and run: python send_all_messages.py

import os
import sys
import django
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from campaigns.models import Campaign, Message
from campaigns.tasks import send_whatsapp_message

def send_campaign_messages(campaign_id):
    """Send all queued messages for a campaign"""
    
    campaign = Campaign.objects.get(id=campaign_id)
    print(f"Campaign: {campaign.template_name}")
    print(f"Status: {campaign.status}")
    
    # Get all queued messages
    messages = Message.objects.filter(campaign_id=campaign_id, status='queued')
    print(f"Found {messages.count()} queued messages")
    
    for msg in messages:
        print(f"\nSending to {msg.phone_number}...")
        
        # Send the message
        send_whatsapp_message(msg.id)
        
        # Check status
        msg.refresh_from_db()
        if msg.status == 'sent':
            print(f"✅ Sent successfully! ID: {msg.message_id[:30]}...")
        else:
            print(f"❌ Failed: {msg.error_message}")
        
        # Wait 2 seconds between messages (rate limiting)
        time.sleep(2)
    
    # Update campaign status if all sent
    remaining = Message.objects.filter(campaign_id=campaign_id, status='queued').count()
    if remaining == 0:
        campaign.status = 'completed'
        campaign.save()
        print(f"\n✅ Campaign completed!")
    
    # Show final stats
    campaign.refresh_from_db()
    print(f"\nFinal Stats:")
    print(f"  Sent: {campaign.sent_count}/{campaign.total_recipients}")
    print(f"  Failed: {campaign.failed_count}")

if __name__ == "__main__":
    campaign_id = input("Enter campaign ID (e.g., 6): ")
    send_campaign_messages(int(campaign_id))
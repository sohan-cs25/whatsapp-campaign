#!/usr/bin/env python
"""
Script to fix campaign counter discrepancies
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from campaigns.models import Campaign, Message
from django.db.models import Count, Q

def sync_campaign_counters(campaign_id):
    """Recalculate campaign counters from actual message statuses"""
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        messages = Message.objects.filter(campaign_id=campaign_id)
        
        # Calculate actual counts based on message statuses
        sent_count = messages.filter(status__in=['sent', 'delivered', 'read']).count()
        delivered_count = messages.filter(status__in=['delivered', 'read']).count()  
        read_count = messages.filter(status='read').count()
        failed_count = messages.filter(status='failed').count()
        
        print(f"Campaign #{campaign_id} - {campaign.template_name}")
        print(f"Before fix:")
        print(f"  Total Recipients: {campaign.total_recipients}")
        print(f"  Sent Count: {campaign.sent_count} -> {sent_count}")
        print(f"  Delivered Count: {campaign.delivered_count} -> {delivered_count}")
        print(f"  Read Count: {campaign.read_count} -> {read_count}")
        print(f"  Failed Count: {campaign.failed_count} -> {failed_count}")
        
        # Update campaign with correct counts
        Campaign.objects.filter(id=campaign_id).update(
            sent_count=sent_count,
            delivered_count=delivered_count,
            read_count=read_count,
            failed_count=failed_count
        )
        
        # Verify the fix
        campaign.refresh_from_db()
        print(f"After fix:")
        print(f"  Sent Count: {campaign.sent_count}")
        print(f"  Delivered Count: {campaign.delivered_count}")
        print(f"  Read Count: {campaign.read_count}")
        print(f"  Failed Count: {campaign.failed_count}")
        print(f"  Success Rate: {campaign.success_rate:.2f}%")
        
        # Validation checks
        total_processed = campaign.sent_count + campaign.failed_count
        if total_processed > campaign.total_recipients:
            print(f"❌ ERROR: Total processed ({total_processed}) > Total recipients ({campaign.total_recipients})")
        elif campaign.delivered_count > campaign.sent_count:
            print(f"❌ ERROR: Delivered ({campaign.delivered_count}) > Sent ({campaign.sent_count})")
        elif campaign.read_count > campaign.delivered_count:
            print(f"❌ ERROR: Read ({campaign.read_count}) > Delivered ({campaign.delivered_count})")
        else:
            print("✅ All counters are now consistent!")
            
        return True
        
    except Campaign.DoesNotExist:
        print(f"Campaign {campaign_id} not found")
        return False
    except Exception as e:
        print(f"Error syncing campaign {campaign_id}: {e}")
        return False

def analyze_all_campaigns():
    """Analyze all campaigns for discrepancies"""
    print("Analyzing all campaigns for counter discrepancies...")
    print("=" * 60)
    
    campaigns = Campaign.objects.all().order_by('-created_at')
    discrepancies_found = 0
    
    for campaign in campaigns:
        messages = Message.objects.filter(campaign_id=campaign.id)
        
        # Calculate what counts should be
        actual_sent = messages.filter(status__in=['sent', 'delivered', 'read']).count()
        actual_delivered = messages.filter(status__in=['delivered', 'read']).count()
        actual_read = messages.filter(status='read').count()
        actual_failed = messages.filter(status='failed').count()
        
        # Check for discrepancies
        has_discrepancy = (
            campaign.sent_count != actual_sent or
            campaign.delivered_count != actual_delivered or
            campaign.read_count != actual_read or
            campaign.failed_count != actual_failed or
            campaign.sent_count > campaign.total_recipients
        )
        
        if has_discrepancy:
            discrepancies_found += 1
            print(f"Campaign #{campaign.id} - {campaign.template_name} - {campaign.status}")
            print(f"  Total: {campaign.total_recipients}")
            print(f"  Sent: {campaign.sent_count} (should be {actual_sent})")
            print(f"  Delivered: {campaign.delivered_count} (should be {actual_delivered})")
            print(f"  Read: {campaign.read_count} (should be {actual_read})")
            print(f"  Failed: {campaign.failed_count} (should be {actual_failed})")
            print()
    
    print(f"Found {discrepancies_found} campaigns with counter discrepancies")
    return discrepancies_found

if __name__ == "__main__":
    # First analyze all campaigns
    analyze_all_campaigns()
    
    print("\n" + "=" * 60)
    print("Fixing campaign #23 (the problematic one)")
    print("=" * 60)
    
    # Fix campaign #23 specifically
    sync_campaign_counters(23)
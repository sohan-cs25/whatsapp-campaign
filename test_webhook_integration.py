#!/usr/bin/env python3
"""
Test script for webhook integration between campaigns and orders
"""
import os
import django
import json

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from campaigns.webhook_processor import process_360dialog_webhook
from campaigns.models import Message, Campaign, WebhookLog
from orders.models import Order
from django.contrib.auth.models import User

def test_campaign_webhook():
    """Test webhook processing for campaign messages"""
    print("=" * 50)
    print("Testing Campaign Webhook Processing")
    print("=" * 50)

    # Sample campaign webhook payload
    campaign_payload = {
        "statuses": [
            {
                "id": "wamid.test_campaign_123",
                "status": "delivered",
                "timestamp": "1704067200",
                "recipient_id": "919876543210"
            }
        ]
    }

    # Create test data
    try:
        user = User.objects.get_or_create(username='test_user')[0]
        campaign = Campaign.objects.get_or_create(
            id=1,
            defaults={
                'user': user,
                'template_name': 'test_template',
                'status': 'running'
            }
        )[0]

        message = Message.objects.get_or_create(
            message_id='wamid.test_campaign_123',
            defaults={
                'campaign': campaign,
                'phone_number': '+919876543210',
                'status': 'sent'
            }
        )[0]

        print(f"✓ Created test campaign message: {message.message_id}")
        print(f"  Initial status: {message.status}")

        # Test webhook processing
        result = process_360dialog_webhook(campaign_payload)

        # Check results
        message.refresh_from_db()
        print(f"  Final status: {message.status}")
        print(f"  Processing result: {result}")

        if message.status == 'delivered' and result:
            print("✅ Campaign webhook processing: PASSED")
        else:
            print("❌ Campaign webhook processing: FAILED")

    except Exception as e:
        print(f"❌ Campaign webhook test failed: {e}")

def test_order_webhook():
    """Test webhook processing for order messages"""
    print("\n" + "=" * 50)
    print("Testing Order Webhook Processing")
    print("=" * 50)

    # Sample order webhook payload
    order_payload = {
        "statuses": [
            {
                "id": "wamid.test_order_456",
                "status": "read",
                "timestamp": "1704067260",
                "recipient_id": "919876543211"
            }
        ]
    }

    # Create test data
    try:
        user = User.objects.get_or_create(username='test_user')[0]

        # Create a ValidatedFile first (required for Order)
        from orders.models import ValidatedFile
        validated_file = ValidatedFile.objects.get_or_create(
            id='550e8400-e29b-41d4-a716-446655440001',
            defaults={
                'user': user,
                'file_name': 'test_orders.xlsx',
                'filetype': 'xlsx'
            }
        )[0]

        order = Order.objects.get_or_create(
            message_id='wamid.test_order_456',
            defaults={
                'validated_file': validated_file,
                'number': '+919876543211',
                'order_items': {'item1': 2, 'item2': 1},
                'amount': 100.50,
                'status': 'sent'
            }
        )[0]

        print(f"✓ Created test order: {order.message_id}")
        print(f"  Initial status: {order.status}")

        # Test webhook processing
        result = process_360dialog_webhook(order_payload)

        # Check results
        order.refresh_from_db()
        print(f"  Final status: {order.status}")
        print(f"  Processing result: {result}")

        if order.status == 'read' and result:
            print("✅ Order webhook processing: PASSED")
        else:
            print("❌ Order webhook processing: FAILED")

    except Exception as e:
        print(f"❌ Order webhook test failed: {e}")

def test_unknown_message_id():
    """Test webhook processing for unknown message ID"""
    print("\n" + "=" * 50)
    print("Testing Unknown Message ID Handling")
    print("=" * 50)

    # Sample webhook payload with unknown message ID
    unknown_payload = {
        "statuses": [
            {
                "id": "wamid.unknown_message_999",
                "status": "delivered",
                "timestamp": "1704067300",
                "recipient_id": "919876543212"
            }
        ]
    }

    try:
        print("✓ Testing unknown message ID: wamid.unknown_message_999")

        # Test webhook processing
        result = process_360dialog_webhook(unknown_payload)

        print(f"  Processing result: {result}")

        if result == False:
            print("✅ Unknown message ID handling: PASSED")
        else:
            print("❌ Unknown message ID handling: FAILED")

    except Exception as e:
        print(f"❌ Unknown message ID test failed: {e}")

def cleanup_test_data():
    """Clean up test data"""
    print("\n" + "=" * 50)
    print("Cleaning up test data...")
    print("=" * 50)

    try:
        # Delete test records
        Message.objects.filter(message_id__startswith='wamid.test_').delete()
        Order.objects.filter(message_id__startswith='wamid.test_').delete()
        print("✓ Cleaned up test messages and orders")

    except Exception as e:
        print(f"⚠️  Cleanup warning: {e}")

if __name__ == "__main__":
    print("Starting Webhook Integration Tests")
    print("=" * 80)

    # Run tests
    test_campaign_webhook()
    test_order_webhook()
    test_unknown_message_id()

    # Cleanup
    cleanup_test_data()

    print("\n" + "=" * 80)
    print("Webhook Integration Tests Completed")
    print("=" * 80)
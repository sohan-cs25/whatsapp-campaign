#!/usr/bin/env python3
"""
Test script for payment success notification flow
Tests the complete webhook → payment processing → WhatsApp message flow
"""

import os
import sys
import django
import json
from datetime import datetime

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
sys.path.append('/home/sohan/whatsapp-campaign')
django.setup()

from orders.models import Order, ValidatedFile, WebhookEvent
from orders.webhook_processor import process_payment_webhook
from unified_webhook_router import route_unified_webhook
from django.contrib.auth.models import User
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_test_order():
    """Create a test order for testing payment success flow"""
    logger.info("🔧 Creating test order...")

    # Get or create test user
    user, created = User.objects.get_or_create(
        username='test_payment_user',
        defaults={
            'email': 'test@example.com',
            'first_name': 'Test',
            'last_name': 'User'
        }
    )

    # Create test validated file
    validated_file = ValidatedFile.objects.create(
        user=user,
        file_name='test_payment_orders.xlsx',
        filetype='xlsx',
        is_processed=True,
        orders_extracted=1
    )

    # Create test order
    order = Order.objects.create(
        validated_file=validated_file,
        number='917702828811',  # Phone number from webhook
        order_items='Test Item:1',
        amount='200=200',
        status='sent',
        payment_status='initiated'
    )

    logger.info(f"✅ Test order created: {order.order_id} for phone {order.number}")
    return order

def create_payment_captured_webhook():
    """Create the payment captured webhook payload"""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "114374441730441",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "917996002222",
                                "phone_number_id": "114392571729051"
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgMOTE3NzAyODI4ODExFQIAEhgJNzM5NjczODQxAA==",
                                    "status": "captured",
                                    "timestamp": "1757920128",
                                    "recipient_id": "917702828811",
                                    "type": "payment",
                                    "payment": {
                                        "reference_id": None,  # Will be set to order.order_id
                                        "amount": {
                                            "value": 200,
                                            "offset": 100
                                        },
                                        "currency": "INR",
                                        "transaction": {
                                            "id": "order_RHn0Oo4XS8CuZM",
                                            "pg_transaction_id": "pay_RHn0QRA9d1Gh4a",
                                            "type": "razorpay",
                                            "status": "success",
                                            "created_timestamp": 1757920127,
                                            "updated_timestamp": 1757920127,
                                            "amount": {
                                                "value": 200,
                                                "offset": 100
                                            },
                                            "currency": "INR",
                                            "method": {
                                                "type": "upi"
                                            }
                                        }
                                    }
                                }
                            ]
                        },
                        "field": "messages"
                    }
                ]
            }
        ]
    }

def test_payment_success_flow():
    """Test the complete payment success notification flow"""

    print("🚀 Starting Payment Success Notification Flow Test")
    print("=" * 60)

    try:
        # Step 1: Create test order
        order = create_test_order()

        # Step 2: Create webhook payload
        webhook_payload = create_payment_captured_webhook()
        # Set the reference_id to our test order's ID
        webhook_payload['entry'][0]['changes'][0]['value']['statuses'][0]['payment']['reference_id'] = order.order_id

        logger.info(f"📥 Webhook payload created with reference_id: {order.order_id}")

        # Step 3: Process webhook through unified router
        logger.info("🔄 Processing webhook through unified router...")
        result = route_unified_webhook(webhook_payload)

        logger.info(f"📊 Webhook routing result: {result}")

        # Step 4: Verify order was updated
        order.refresh_from_db()

        print("\n📋 Order Status After Webhook Processing:")
        print(f"  Order ID: {order.order_id}")
        print(f"  Payment Status: {order.payment_status}")
        print(f"  Payment Amount Captured: ₹{order.payment_amount_captured}")
        print(f"  Payment Method: {order.payment_method}")
        print(f"  Payment Reference ID: {order.payment_reference_id}")
        print(f"  Payment Captured At: {order.payment_captured_at}")

        print(f"\n💬 Payment Success Message Status:")
        print(f"  Message Sent: {order.payment_success_message_sent}")
        print(f"  Message Status: {order.payment_success_message_status}")
        print(f"  Message ID: {order.payment_success_message_id}")
        print(f"  Sent At: {order.payment_success_sent_at}")

        # Step 5: Check webhook event was created
        webhook_events = WebhookEvent.objects.filter(
            event_type='payment_status',
            payment_reference_id=order.order_id
        ).order_by('-received_at')

        print(f"\n📝 Webhook Events Created: {webhook_events.count()}")
        if webhook_events.exists():
            latest_event = webhook_events.first()
            print(f"  Latest Event ID: {latest_event.id}")
            print(f"  Processed: {latest_event.processed}")
            print(f"  Processed At: {latest_event.processed_at}")
            print(f"  Linked Order: {latest_event.order}")

        # Step 6: Verify expected outcomes
        print(f"\n✅ Test Results:")

        success_checks = [
            ("Payment status updated to 'completed'", order.payment_status == 'completed'),
            ("Payment amount captured correctly", order.payment_amount_captured == 2.00),
            ("Payment method set to 'upi'", order.payment_method == 'upi'),
            ("Payment reference ID set", bool(order.payment_reference_id)),
            ("Payment success message sent", order.payment_success_message_sent),
            ("Payment success message has status", bool(order.payment_success_message_status)),
            ("Webhook event created", webhook_events.exists()),
            ("Webhook event processed", webhook_events.exists() and webhook_events.first().processed)
        ]

        all_passed = True
        for check_name, passed in success_checks:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status} - {check_name}")
            if not passed:
                all_passed = False

        print(f"\n🎯 Overall Test Result: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")

        # Step 7: Cleanup (optional)
        cleanup = input("\n🧹 Clean up test data? (y/n): ").lower().strip()
        if cleanup == 'y':
            order.delete()
            order.validated_file.delete()
            webhook_events.delete()
            print("✅ Test data cleaned up")
        else:
            print(f"🔍 Test data preserved - Order ID: {order.order_id}")

        return all_passed

    except Exception as e:
        logger.error(f"❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def test_api_endpoint():
    """Test the API endpoint for resending payment success messages"""
    logger.info("🔧 Testing API endpoint...")

    # This would require a proper Django test client setup
    # For now, we'll just verify the endpoint exists
    from orders.urls import urlpatterns

    payment_success_endpoints = [
        url for url in urlpatterns
        if 'resend-payment-success' in str(url.pattern)
    ]

    if payment_success_endpoints:
        print("✅ Payment success API endpoint found in URLs")
        return True
    else:
        print("❌ Payment success API endpoint NOT found in URLs")
        return False

if __name__ == "__main__":
    print("🧪 Payment Success Notification Flow Test Suite")
    print("=" * 60)

    # Test 1: API endpoint exists
    api_test_passed = test_api_endpoint()

    # Test 2: Complete flow test
    flow_test_passed = test_payment_success_flow()

    print(f"\n🎯 Final Results:")
    print(f"  API Endpoint Test: {'✅ PASS' if api_test_passed else '❌ FAIL'}")
    print(f"  Complete Flow Test: {'✅ PASS' if flow_test_passed else '❌ FAIL'}")

    if api_test_passed and flow_test_passed:
        print(f"\n🎉 ALL TESTS PASSED! Payment success notification system is working correctly.")
    else:
        print(f"\n⚠️  Some tests failed. Please check the implementation.")
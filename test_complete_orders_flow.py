#!/usr/bin/env python3
"""
Complete Orders Flow Test
Tests the entire order processing workflow including:
1. File upload and parsing
2. Order creation with WhatsApp service
3. Webhook processing (message status + payment)
4. Payment tracking
"""

import os
import sys
import django
import json
import tempfile
from decimal import Decimal

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from orders.models import Order, ValidatedFile
from orders.whatsapp_service import OrderWhatsAppService
from orders.webhook_processor import process_order_webhook_status, process_payment_webhook
from unified_webhook_router import route_unified_webhook
from django.contrib.auth.models import User
from django.utils import timezone


def create_test_csv():
    """Create test CSV file with order data"""
    csv_content = """Phone/Name,Order Items,Amount
919474816594,"Apples:1,Pears:2","150+200=350"
919876543210,"Mango:3","450=450"
919123456789,"Bananas:2,Oranges:1","100+200=300"
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(csv_content)
        return f.name


def test_order_creation():
    """Test order creation from validated file"""
    print("🔄 Testing Order Creation...")

    # Create test user
    user, _ = User.objects.get_or_create(username='testuser')

    # Create validated file
    validated_file = ValidatedFile.objects.create(
        user=user,
        file_name='test_orders.csv',
        filetype='csv'
    )

    # Create test orders
    orders = [
        Order.objects.create(
            validated_file=validated_file,
            number='919474816594',
            order_items='Apples:1,Pears:2',
            amount='150+200=350'
        ),
        Order.objects.create(
            validated_file=validated_file,
            number='919876543210',
            order_items='Mango:3',
            amount='450=450'
        ),
        Order.objects.create(
            validated_file=validated_file,
            number='919123456789',
            order_items='Bananas:2,Oranges:1',
            amount='100+200=300'
        )
    ]

    print(f"✅ Created {len(orders)} test orders")
    for order in orders:
        print(f"   Order {order.order_id}: {order.number} - {order.order_items}")

    return orders


def test_whatsapp_payload_generation():
    """Test WhatsApp payload generation"""
    print("\n🔄 Testing WhatsApp Payload Generation...")

    service = OrderWhatsAppService()
    orders = Order.objects.all()[:1]  # Test with first order

    for order in orders:
        payload = service.build_order_details_payload(order)
        print(f"✅ Generated payload for order {order.order_id}")
        print(f"   Phone: {payload['to']}")
        print(f"   Template: {payload['template']['name']}")

        # Verify order details structure
        order_details = payload['template']['components'][0]['parameters'][0]['action']['order_details']
        print(f"   Currency: {order_details['currency']}")
        print(f"   Reference ID: {order_details['reference_id']}")
        print(f"   Items count: {len(order_details['order']['items'])}")
        print(f"   Total amount: ₹{order_details['total_amount']['value'] / 100}")

        return payload


def test_message_status_webhook():
    """Test message status webhook processing"""
    print("\n🔄 Testing Message Status Webhook...")

    order = Order.objects.first()
    if not order:
        print("❌ No orders found for webhook test")
        return

    # Simulate order being sent
    order.whatsapp_message_id = 'wamid_test123'
    order.status = 'sent'
    order.save()

    # Test delivered webhook
    delivered_webhook = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid_test123",
                        "status": "delivered",
                        "timestamp": "1694767890",
                        "recipient_id": "919474816594"
                    }]
                }
            }]
        }]
    }

    print(f"   Processing delivered webhook for order {order.order_id}")
    result = process_order_webhook_status(delivered_webhook)

    # Reload order
    order.refresh_from_db()
    print(f"✅ Webhook processed: {result}")
    print(f"   Order status: {order.status}")
    print(f"   Delivered at: {order.delivered_at}")

    # Test read webhook
    read_webhook = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid_test123",
                        "status": "read",
                        "timestamp": "1694767900",
                        "recipient_id": "919474816594"
                    }]
                }
            }]
        }]
    }

    print(f"   Processing read webhook for order {order.order_id}")
    result = process_order_webhook_status(read_webhook)

    # Reload order
    order.refresh_from_db()
    print(f"✅ Webhook processed: {result}")
    print(f"   Order status: {order.status}")
    print(f"   Read at: {order.read_at}")


def test_payment_webhook():
    """Test payment webhook processing"""
    print("\n🔄 Testing Payment Webhook...")

    order = Order.objects.first()
    if not order:
        print("❌ No orders found for payment test")
        return

    # Payment webhook payload (from your example)
    payment_webhook = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid_payment123",
                        "status": "captured",
                        "type": "payment",
                        "payment": {
                            "reference_id": order.order_id,  # Use our order_id
                            "amount": {"value": 35000, "offset": 100},  # ₹350
                            "currency": "INR",
                            "transaction": {
                                "id": "order_RHlQgzJ1DYSpcM",
                                "pg_transaction_id": "pay_RHlQj5OMDHzaEd",
                                "type": "razorpay",
                                "status": "success",
                                "method": {"type": "upi"}
                            }
                        }
                    }]
                }
            }]
        }]
    }

    print(f"   Processing payment webhook for order {order.order_id}")
    result = process_payment_webhook(payment_webhook)

    # Reload order
    order.refresh_from_db()
    print(f"✅ Payment webhook processed: {result}")
    print(f"   Payment status: {order.payment_status}")
    print(f"   Payment method: {order.payment_method}")
    print(f"   Amount captured: ₹{order.payment_amount_captured}")
    print(f"   Razorpay order ID: {order.razorpay_order_id}")
    print(f"   Razorpay payment ID: {order.payment_reference_id}")
    print(f"   Payment captured at: {order.payment_captured_at}")
    print(f"   Webhook data stored: {bool(order.payment_webhook_data)}")


def test_unified_webhook_router():
    """Test unified webhook router"""
    print("\n🔄 Testing Unified Webhook Router...")

    order = Order.objects.first()
    if not order:
        print("❌ No orders found for router test")
        return

    # Test message status routing
    message_webhook = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": order.whatsapp_message_id,
                        "status": "delivered",
                        "timestamp": "1694767890"
                    }]
                }
            }]
        }]
    }

    print("   Testing message status routing...")
    result = route_unified_webhook(message_webhook)
    print(f"✅ Message webhook routed to: {result['processor_used']}")
    print(f"   Webhook type detected: {result['webhook_type']}")

    # Test payment routing
    payment_webhook = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid_payment456",
                        "status": "captured",
                        "type": "payment",
                        "payment": {
                            "reference_id": order.order_id,
                            "amount": {"value": 35000, "offset": 100}
                        }
                    }]
                }
            }]
        }]
    }

    print("   Testing payment routing...")
    result = route_unified_webhook(payment_webhook)
    print(f"✅ Payment webhook routed to: {result['processor_used']}")
    print(f"   Webhook type detected: {result['webhook_type']}")


def test_complete_flow():
    """Run complete test flow"""
    print("🚀 Starting Complete Orders Flow Test\n")

    try:
        # 1. Test order creation
        orders = test_order_creation()

        # 2. Test WhatsApp payload generation
        test_whatsapp_payload_generation()

        # 3. Test message status webhooks
        test_message_status_webhook()

        # 4. Test payment webhooks
        test_payment_webhook()

        # 5. Test unified router
        test_unified_webhook_router()

        print("\n🎉 All Tests Completed Successfully!")

        # Print final order state
        print("\n📊 Final Order States:")
        for order in Order.objects.all():
            print(f"   Order {order.order_id}:")
            print(f"     - Message Status: {order.status}")
            print(f"     - Payment Status: {order.payment_status}")
            print(f"     - WhatsApp Message ID: {order.whatsapp_message_id}")
            print(f"     - Payment Amount: ₹{order.payment_amount_captured or 0}")
            print()

        return True

    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_complete_flow()
    sys.exit(0 if success else 1)
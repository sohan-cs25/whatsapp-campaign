#!/usr/bin/env python3
"""
Test single item parsing edge cases
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_campaign.settings')
django.setup()

from orders.whatsapp_service import OrderWhatsAppService


def test_single_item_cases():
    """Test various single item amount formats"""

    service = OrderWhatsAppService()

    test_cases = [
        # (order_items, amount_str, expected_description)
        ("Apples:1", "1", "Single item, amount without equals"),
        ("Apples:1", "1=1", "Single item, amount with equals"),
        ("Apples:2", "50", "Single item, quantity > 1, no equals"),
        ("Apples:2", "50=50", "Single item, quantity > 1, with equals"),
        ("Apples:1,Pears:1", "1+1=2", "Two items, standard format"),
        ("Apples:1,Pears:1", "2", "Two items, total only"),
        ("Mango:3", "150", "Single item, quantity 3, no equals"),
    ]

    print("🔄 Testing Single Item Parsing Cases\n")

    for order_items_str, amount_str, description in test_cases:
        print(f"Testing: {description}")
        print(f"  Input: Items='{order_items_str}', Amount='{amount_str}'")

        try:
            items, total_paisa = service.parse_order_items(order_items_str, amount_str)

            print(f"  Output:")
            print(f"    Total: ₹{total_paisa / 100}")
            print(f"    Items ({len(items)}):")

            for item in items:
                item_amount = item['amount']['value'] / 100
                print(f"      - {item['name']} x{item['quantity']} = ₹{item_amount}")

            # Verify totals match
            item_total = sum(item['amount']['value'] for item in items)
            if item_total == total_paisa:
                print(f"  ✅ Totals match: ₹{item_total / 100}")
            else:
                print(f"  ❌ Total mismatch: Items=₹{item_total / 100}, Expected=₹{total_paisa / 100}")

        except Exception as e:
            print(f"  ❌ Error: {str(e)}")

        print()


if __name__ == '__main__':
    test_single_item_cases()
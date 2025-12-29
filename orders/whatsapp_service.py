"""
WhatsApp messaging service for orders
Handles order confirmation messages using order_details template
"""

import logging
import time
from typing import Dict, List, Any, Tuple
from django.utils import timezone

logger = logging.getLogger(__name__)


class OrderWhatsAppService:
    """Service for sending WhatsApp order confirmation messages"""

    def __init__(self):
        """Initialize WhatsApp service using campaigns app client"""
        try:
            from campaigns.whatsapp_360_client import WhatsApp360Client
            self.client = WhatsApp360Client()
            logger.info("WhatsApp client initialized successfully")
        except ImportError as e:
            logger.error(f"Failed to import WhatsApp client: {e}")
            raise e

    def parse_order_items(self, order_items_str: str, total_amount_str: str) -> Tuple[List[Dict[str, Any]], int]:
        """
        Parse order items and amounts from separate strings

        Args:
            order_items_str: "Apples:2,Pears:1" (items:quantity separated by comma)
            total_amount_str: "100+200=300" (individual amounts + total)

        Returns:
            Tuple of (items list, total_amount_paisa)
        """
        items = []
        total_amount = 0

        try:
            # Parse total amount string "100+200=300"
            individual_amounts = []
            if '=' in total_amount_str:
                amounts_part, total_part = total_amount_str.split('=', 1)
                total_amount = int(float(total_part.strip()))

                # Parse individual amounts
                amount_strs = [amt.strip() for amt in amounts_part.split('+')]
                individual_amounts = [int(float(amt)) for amt in amount_strs if amt]
            else:
                # Fallback: use the whole string as total
                total_amount = int(float(total_amount_str.strip()))

            # Parse order items string "Apples:2,Pears:1"
            item_pairs = [item.strip() for item in order_items_str.split(',')]
            parsed_items = []

            for item_pair in item_pairs:
                if ':' in item_pair:
                    item_name, quantity_str = item_pair.split(':', 1)
                    item_name = item_name.strip()
                    quantity = int(quantity_str.strip())
                    parsed_items.append((item_name, quantity))

            # Match items with their individual amounts
            for i, (item_name, quantity) in enumerate(parsed_items):
                # Use individual amount if available, otherwise split total equally
                if i < len(individual_amounts):
                    item_amount = individual_amounts[i]
                else:
                    # Fallback: equal distribution
                    item_amount = int(total_amount / len(parsed_items)) if parsed_items else total_amount

                items.append({
                    "amount": {
                        "offset": 100,  # For paisa conversion (multiply by 100)
                        "value": item_amount * 100  # Convert to paisa
                    },
                    "name": item_name,
                    "quantity": quantity,
                    "country_of_origin": "India",
                    "importer_name": "Farmveda"
                })

                logger.debug("Parsed item: %s x%d = ₹%d (value: %d paisa)",
                           item_name, quantity, item_amount, item_amount * 100)

            return items, total_amount * 100  # Return total in paisa

        except Exception as e:
            logger.error("Error parsing order items '%s' with amounts '%s': %s",
                        order_items_str, total_amount_str, str(e))
            # Fallback: create single item
            return [{
                "amount": {
                    "offset": 100,
                    "value": total_amount * 100 if total_amount else 0
                },
                "name": "Order Items",
                "quantity": 1,
                "country_of_origin": "India",
                "importer_name": "Farmveda"
            }], total_amount * 100

    def build_order_details_payload(self, order) -> Dict[str, Any]:
        """
        Build order_details template payload from Order object

        Args:
            order: Order model instance

        Returns:
            Dict containing the WhatsApp API payload
        """
        try:
            logger.info(f"🔍 Building payload for Order {order.order_id}")
            logger.info(f"   Raw order.order_items: '{order.order_items}' (type: {type(order.order_items)})")
            logger.info(f"   Raw order.amount: '{order.amount}' (type: {type(order.amount)})")

            # Get order items string: "Apples:2,Pears:1"
            if hasattr(order, 'order_items'):
                if isinstance(order.order_items, str):
                    order_items_str = order.order_items
                elif isinstance(order.order_items, dict) and 'items' in order.order_items:
                    order_items_str = order.order_items['items']
                else:
                    order_items_str = str(order.order_items)
            else:
                order_items_str = "Order Items:1"

            # Get total amount string: "100+200=300"
            # Assuming order.amount field contains the amount breakdown
            if hasattr(order, 'amount') and isinstance(order.amount, str):
                total_amount_str = order.amount
            else:
                # Fallback: create simple format
                amount_value = float(order.amount) if hasattr(order, 'amount') else 0
                total_amount_str = f"{amount_value}={amount_value}"

            logger.info(f"   Processed order_items_str: '{order_items_str}'")
            logger.info(f"   Processed total_amount_str: '{total_amount_str}'")

            # Parse items and amounts
            items, total_value_paisa = self.parse_order_items(order_items_str, total_amount_str)

            logger.info(f"   Parsed items count: {len(items)}")
            logger.info(f"   Total amount in paisa: {total_value_paisa}")
            for i, item in enumerate(items):
                logger.info(f"   Item {i+1}: {item['name']} x{item['quantity']} = ₹{item['amount']['value']/100}")

            # Build the complete payload
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": order.number,
                "type": "template",
                "template": {
                    "name": "sample_order_details",
                    "language": {
                        "policy": "deterministic",
                        "code": "en"
                    },
                    "components": [
                        {
                            "type": "button",
                            "sub_type": "order_details",
                            "index": 0,
                            "parameters": [
                                {
                                    "type": "action",
                                    "action": {
                                        "order_details": {
                                            "currency": "INR",
                                            "order": {
                                                "items": items,
                                                "status": "pending",
                                                "subtotal": {
                                                    "offset": 100,
                                                    "value": total_value_paisa
                                                }
                                            },
                                            "payment_settings": [
                                                {
                                                    "type": "payment_gateway",
                                                    "payment_gateway": {
                                                        "type": "razorpay",
                                                        "configuration_name": "WhatsappGroups-Payments"
                                                    }
                                                }
                                            ],
                                            "reference_id": order.order_id,
                                            "total_amount": {
                                                "offset": 100,
                                                "value": total_value_paisa
                                            },
                                            "type": "physical-goods"
                                        }
                                    }
                                }
                            ]
                        }
                    ]
                }
            }

            logger.info("✅ Built payload for order %s to %s - Items: %s",
                       order.order_id, order.number, order_items_str)

            # Log the complete payload for debugging
            logger.info(f"📤 COMPLETE PAYLOAD for Order {order.order_id}:")
            logger.info(f"   Recipient: {payload['to']}")
            logger.info(f"   Template: {payload['template']['name']}")
            logger.info(f"   Currency: {payload['template']['components'][0]['parameters'][0]['action']['order_details']['currency']}")
            logger.info(f"   Reference ID: {payload['template']['components'][0]['parameters'][0]['action']['order_details']['reference_id']}")
            logger.info(f"   Total Amount: ₹{payload['template']['components'][0]['parameters'][0]['action']['order_details']['total_amount']['value'] / 100}")
            logger.info(f"   Items in payload: {len(payload['template']['components'][0]['parameters'][0]['action']['order_details']['order']['items'])}")

            # Log JSON payload (truncated for readability)
            import json
            logger.info(f"📋 JSON PAYLOAD:\n{json.dumps(payload, indent=2)}")

            return payload

        except Exception as e:
            logger.error(f"Error building payload for order {order.order_id}: {str(e)}")
            raise e

    def send_order_message(self, order) -> Dict[str, Any]:
        """
        Send single order confirmation with order_details template

        Args:
            order: Order model instance

        Returns:
            Dict containing the API response
        """
        try:
            logger.info(f"Sending order message for {order.order_id} to {order.number}")

            # Build the payload
            payload = self.build_order_details_payload(order)

            # Update order status to 'sending'
            order.status = 'sending'
            order.save()

            # Send via WhatsApp client
            response = self.client.send_message(payload)

            # Update order based on response
            if response and response.get('success', False):
                order.status = 'sent'
                order.sent_at = timezone.now()
                order.whatsapp_message_id = response.get('message_id', '')
                order.whatsapp_response_code = 200
                order.whatsapp_response_json = response
                logger.info(f"✅ Order {order.order_id} sent successfully")
            else:
                order.status = 'failed'
                order.whatsapp_response_code = response.get('status_code', 400) if response else 500
                order.whatsapp_response_json = response or {'error': 'No response from WhatsApp API'}
                logger.warning(f"❌ Order {order.order_id} failed to send: {order.whatsapp_response_json}")

            order.save()
            return response or {'success': False, 'error': 'No response'}

        except Exception as e:
            logger.error(f"❌ Error sending order {order.order_id}: {str(e)}")

            # Update order status to failed
            order.status = 'failed'
            order.whatsapp_response_json = {'error': str(e)}
            order.save()

            raise e

    def send_bulk_orders(self, orders, delay_seconds: float = 2.0) -> Dict[str, Any]:
        """
        Send multiple order confirmations with delay between messages

        Args:
            orders: QuerySet or list of Order instances
            delay_seconds: Delay between messages (default: 2.0 seconds)

        Returns:
            Dict containing bulk sending results
        """
        results = {
            'sent_count': 0,
            'failed_count': 0,
            'details': [],
            'total_time_seconds': 0
        }

        start_time = time.time()
        total_orders = len(orders)

        logger.info(f"Starting bulk send for {total_orders} orders with {delay_seconds}s delay")

        for index, order in enumerate(orders):
            try:
                logger.info(f"Processing order {index + 1}/{total_orders}: {order.order_id}")

                response = self.send_order_message(order)

                if order.status == 'sent':
                    results['sent_count'] += 1
                else:
                    results['failed_count'] += 1

                results['details'].append({
                    'order_id': order.order_id,
                    'number': order.number,
                    'status': order.status,
                    'message_id': getattr(order, 'whatsapp_message_id', ''),
                    'response': response
                })

                # Add delay between messages (except for the last one)
                if index < total_orders - 1:
                    logger.info(f"⏳ Waiting {delay_seconds} seconds before next message...")
                    time.sleep(delay_seconds)

            except Exception as e:
                results['failed_count'] += 1
                results['details'].append({
                    'order_id': order.order_id,
                    'number': order.number,
                    'status': 'failed',
                    'error': str(e)
                })
                logger.error(f"❌ Error processing order {order.order_id}: {str(e)}")

                # Still maintain delay even on error
                if index < total_orders - 1:
                    time.sleep(delay_seconds)

        results['total_time_seconds'] = int(time.time() - start_time)

        logger.info(f"📊 Bulk send complete: {results['sent_count']} sent, {results['failed_count']} failed in {results['total_time_seconds']}s")

        return results

    def send_payment_success_message(self, order, payment_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send payment success confirmation message using template

        Args:
            order: Order model instance
            payment_data: Payment webhook data containing amount, method, transaction details

        Returns:
            Dict containing the API response
        """
        try:
            logger.info(f"Sending payment success message for order {order.order_id} to {order.number}")

            # Extract payment data from webhook
            amount_value = payment_data.get('amount', {}).get('value', 0)
            amount_offset = payment_data.get('amount', {}).get('offset', 100)
            actual_amount = amount_value / amount_offset if amount_offset else 0  # 200/100 = 2.00

            payment_method = payment_data.get('transaction', {}).get('method', {}).get('type', 'Unknown')
            payment_method_display = payment_method.upper() if payment_method else 'Unknown'

            transaction_id = payment_data.get('transaction', {}).get('pg_transaction_id', 'N/A')
            reference_id = payment_data.get('reference_id', order.order_id)

            # Build template message payload
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": order.number,
                "type": "template",
                "template": {
                    "name": "payment_success_confirmation",
                    "language": {
                        "policy": "deterministic",
                        "code": "en"
                    },
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {
                                    "type": "text",
                                    "text": reference_id  # {{1}} - Order/Reference ID
                                },
                                {
                                    "type": "text",
                                    "text": f"{actual_amount:.2f}"  # {{2}} - Amount in rupees
                                },
                                {
                                    "type": "text",
                                    "text": payment_method_display  # {{3}} - Payment method
                                },
                                {
                                    "type": "text",
                                    "text": transaction_id  # {{4}} - Transaction ID
                                }
                            ]
                        }
                    ]
                }
            }

            logger.info(f"Payment success template variables: Order={reference_id}, Amount=₹{actual_amount:.2f}, Method={payment_method_display}, TxnID={transaction_id}")

            # Send via WhatsApp client
            response = self.client.send_message(payload)

            # Update order payment success tracking
            if response and response.get('success', False):
                order.payment_success_message_sent = True
                order.payment_success_sent_at = timezone.now()
                order.payment_success_message_id = response.get('message_id', '')
                order.payment_success_message_status = 'sent'
                logger.info(f"✅ Payment success message for order {order.order_id} sent successfully")
            else:
                order.payment_success_message_sent = False
                order.payment_success_message_status = 'failed'
                logger.warning(f"❌ Payment success message for order {order.order_id} failed: {response}")

            order.save()
            return response or {'success': False, 'error': 'No response'}

        except Exception as e:
            logger.error(f"❌ Error sending payment success message for order {order.order_id}: {str(e)}")

            # Update order status to failed
            order.payment_success_message_sent = False
            order.payment_success_message_status = 'failed'
            order.save()

            raise e
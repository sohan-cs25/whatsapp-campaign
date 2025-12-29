import logging
from django.utils import timezone
from django.db import models

logger = logging.getLogger('orders')


def process_order_webhook_status(payload):
    """
    Process 360dialog webhook payload for orders
    This function handles status updates for Order model messages
    """
    from .models import Order  # Import here to avoid circular import

    try:
        # Handle Meta/WhatsApp Cloud API webhook structure
        if 'entry' in payload:
            # Meta webhook format
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    if 'statuses' in value:
                        payload = value  # Extract the nested value
                        break

        # Process status updates
        if 'statuses' in payload:
            for status_update in payload['statuses']:
                message_id = status_update.get('id')
                status = status_update.get('status')
                timestamp = status_update.get('timestamp')
                recipient_id = status_update.get('recipient_id')

                logger.info(f"Processing order status update: {message_id} -> {status}")

                # Find the order in our database
                try:
                    order = Order.objects.get(whatsapp_message_id=message_id)
                    old_status = order.status

                    # Update order status based on webhook
                    if status == 'sent':
                        # Ignore webhook 'sent' status - order already marked as sent on API success
                        # Just log for debugging purposes
                        logger.info(f"Webhook 'sent' received for order {message_id} - already handled on API success")

                    elif status == 'delivered':
                        # Only update if order is not already delivered or read
                        if order.status not in ['delivered', 'read']:
                            order.status = 'delivered'
                            order.delivered_at = timezone.now()
                            logger.info(f"Order {message_id} marked as delivered")
                        else:
                            logger.info(f"Order {message_id} already delivered/read, skipping duplicate webhook")

                    elif status == 'read':
                        # Only update if order is not already read
                        if order.status != 'read':
                            order.status = 'read'
                            order.read_at = timezone.now()
                            logger.info(f"Order {message_id} marked as read")
                        else:
                            logger.info(f"Order {message_id} already read, skipping duplicate webhook")

                    elif status == 'failed':
                        # Only update if order is not already failed
                        if order.status != 'failed':
                            order.status = 'failed'

                            # Extract error details
                            errors = status_update.get('errors', [])
                            if errors:
                                error_msg = f"Error {errors[0].get('code')}: {errors[0].get('title')}"
                                # Store error in response_json for tracking
                                order.whatsapp_response_json = {
                                    'error': error_msg,
                                    'webhook_errors': errors,
                                    'failed_at': timezone.now().isoformat()
                                }

                            logger.error(f"Order {message_id} failed: {order.whatsapp_response_json.get('error', 'Unknown error')}")
                        else:
                            logger.info(f"Order {message_id} already failed, skipping duplicate webhook")

                    order.save()

                    logger.info(f"Updated order {message_id}: {old_status} -> {status}")

                except Order.DoesNotExist:
                    logger.warning(f"Order not found for message ID: {message_id}")
                    return False
                except Exception as e:
                    logger.error(f"Error updating order {message_id}: {e}")
                    return False

        # Process incoming messages (if needed for orders)
        if 'messages' in payload:
            for incoming_msg in payload['messages']:
                logger.info(f"Received incoming order message: {incoming_msg}")

        # Process errors
        if 'errors' in payload:
            for error in payload['errors']:
                logger.error(f"360dialog order error: {error}")

        return True

    except Exception as e:
        logger.error(f"Error processing order webhook: {e}")
        return False


def process_payment_webhook(payload):
    """
    Process payment webhook from 360dialog/Razorpay
    Handles payment status updates for Order model

    Expected payload format:
    {
      "object": "whatsapp_business_account",
      "entry": [{
        "changes": [{
          "value": {
            "statuses": [{
              "id": "wamid_xyz",
              "status": "captured",
              "type": "payment",
              "payment": {
                "reference_id": "1509251",
                "amount": {"value": 200, "offset": 100},
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
    """
    from .models import Order  # Import here to avoid circular import

    try:
        logger.info("Processing payment webhook...")

        # Handle Meta/WhatsApp webhook structure
        statuses = []
        if 'entry' in payload:
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    if 'statuses' in value:
                        statuses.extend(value['statuses'])

        # Process payment status updates
        for status_update in statuses:
            if status_update.get('type') != 'payment':
                continue  # Skip non-payment statuses

            payment_data = status_update.get('payment', {})
            reference_id = payment_data.get('reference_id')  # This should be our order_id
            payment_status = status_update.get('status')    # captured, failed, etc.
            transaction = payment_data.get('transaction', {})

            logger.info(f"Processing payment webhook: reference_id={reference_id}, status={payment_status}")

            if not reference_id:
                logger.warning("Payment webhook missing reference_id")
                continue

            # Find the order by reference_id (which should be our order_id)
            try:
                order = Order.objects.get(order_id=reference_id)
                old_payment_status = order.payment_status

                # Extract payment details
                amount_data = payment_data.get('amount', {})
                payment_amount = amount_data.get('value', 0) / 100  # Convert from paisa to rupees

                # Extract transaction details
                razorpay_order_id = transaction.get('id', '')
                razorpay_payment_id = transaction.get('pg_transaction_id', '')
                payment_method_data = transaction.get('method', {})
                payment_method = payment_method_data.get('type', 'unknown')

                # Update order based on payment status
                if payment_status == 'captured':
                    order.payment_status = 'completed'
                    order.payment_captured_at = timezone.now()
                    logger.info(f"Payment captured for order {reference_id}: ₹{payment_amount}")

                    # Update payment tracking fields before saving
                    order.payment_reference_id = razorpay_payment_id
                    order.razorpay_order_id = razorpay_order_id
                    order.payment_method = payment_method
                    order.payment_amount_captured = payment_amount
                    order.payment_webhook_data = payload
                    order.save()

                    # Send payment success message (only if not already sent)
                    if not order.payment_success_message_sent:
                        try:
                            from .whatsapp_service import OrderWhatsAppService
                            whatsapp_service = OrderWhatsAppService()

                            logger.info(f"🚀 Triggering payment success message for order {reference_id}")
                            response = whatsapp_service.send_payment_success_message(order, payment_data)

                            if response and response.get('success', False):
                                logger.info(f"✅ Payment success message sent for order {reference_id}")
                            else:
                                logger.warning(f"❌ Failed to send payment success message for order {reference_id}: {response}")

                        except Exception as e:
                            logger.error(f"❌ Error sending payment success message for order {reference_id}: {str(e)}")
                    else:
                        logger.info(f"ℹ️ Payment success message already sent for order {reference_id}, skipping")

                elif payment_status == 'failed':
                    order.payment_status = 'failed'
                    order.payment_reference_id = razorpay_payment_id
                    order.razorpay_order_id = razorpay_order_id
                    order.payment_method = payment_method
                    order.payment_webhook_data = payload
                    order.save()
                    logger.warning(f"Payment failed for order {reference_id}")

                elif payment_status == 'initiated':
                    order.payment_status = 'initiated'
                    order.payment_reference_id = razorpay_payment_id
                    order.razorpay_order_id = razorpay_order_id
                    order.payment_method = payment_method
                    order.payment_webhook_data = payload
                    order.save()
                    logger.info(f"Payment initiated for order {reference_id}")

                logger.info(f"Updated payment for order {reference_id}: {old_payment_status} -> {order.payment_status}")
                logger.info(f"Payment details: method={payment_method}, amount=₹{payment_amount}, razorpay_payment_id={razorpay_payment_id}")

            except Order.DoesNotExist:
                logger.warning(f"Order not found for payment reference_id: {reference_id}")
                return False
            except Exception as e:
                logger.error(f"Error updating payment for order {reference_id}: {e}")
                return False

        return True

    except Exception as e:
        logger.error(f"Error processing payment webhook: {e}")
        return False
"""
Unified webhook router for both campaigns and orders
Routes webhooks based on content analysis to appropriate processors
"""

import logging
import json
from typing import Dict, Any, Optional
from django.utils import timezone

logger = logging.getLogger(__name__)


class UnifiedWebhookRouter:
    """Routes webhooks to appropriate processors based on content analysis"""

    def __init__(self):
        self.logger = logger

    def analyze_webhook_type(self, payload: Dict[str, Any]) -> str:
        """
        Analyze webhook payload to determine routing destination

        Returns:
            'campaign_message_status' - For campaign message status updates
            'order_message_status' - For order message status updates
            'payment_status' - For payment webhook updates
            'unknown' - Cannot determine type
        """
        try:
            # Check if it's a payment webhook
            if self._is_payment_webhook(payload):
                return 'payment_status'

            # Check if it's a message status webhook
            if self._is_message_status_webhook(payload):
                # Determine if it's campaign or order related
                message_ids = self._extract_message_ids(payload)

                for message_id in message_ids:
                    # Check if message_id belongs to campaigns
                    if self._is_campaign_message(message_id):
                        return 'campaign_message_status'

                    # Check if message_id belongs to orders
                    if self._is_order_message(message_id):
                        return 'order_message_status'

                # If we can't determine, default to campaign for backward compatibility
                self.logger.warning(f"Cannot determine message owner for IDs {message_ids}, defaulting to campaign")
                return 'campaign_message_status'

            self.logger.warning(f"Unknown webhook type: {json.dumps(payload, indent=2)}")
            return 'unknown'

        except Exception as e:
            self.logger.error(f"Error analyzing webhook type: {e}")
            return 'unknown'

    def _is_payment_webhook(self, payload: Dict[str, Any]) -> bool:
        """Check if webhook contains payment status updates"""
        try:
            # Look for payment-specific indicators in the payload
            if 'entry' in payload:
                for entry in payload.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        if 'statuses' in value:
                            for status in value['statuses']:
                                # Payment webhooks have type: "payment"
                                if status.get('type') == 'payment':
                                    return True
                                # Payment webhooks contain payment data
                                if 'payment' in status:
                                    return True
            return False
        except Exception:
            return False

    def _is_message_status_webhook(self, payload: Dict[str, Any]) -> bool:
        """Check if webhook contains message status updates"""
        try:
            # Look for message status indicators
            if 'entry' in payload:
                for entry in payload.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        # Message status webhooks have 'statuses' array
                        if 'statuses' in value:
                            return True

            # Direct status format (fallback)
            if 'statuses' in payload:
                return True

            return False
        except Exception:
            return False

    def _extract_message_ids(self, payload: Dict[str, Any]) -> list:
        """Extract message IDs from webhook payload"""
        message_ids = []
        try:
            # Handle Meta/WhatsApp webhook structure
            if 'entry' in payload:
                for entry in payload.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        if 'statuses' in value:
                            for status in value['statuses']:
                                if 'id' in status:
                                    message_ids.append(status['id'])

            # Handle direct status format
            elif 'statuses' in payload:
                for status in payload['statuses']:
                    if 'id' in status:
                        message_ids.append(status['id'])

        except Exception as e:
            self.logger.error(f"Error extracting message IDs: {e}")

        return message_ids

    def _extract_payment_reference_id(self, payload: Dict[str, Any]) -> str:
        """Extract payment reference ID from webhook payload"""
        try:
            # Handle Meta/WhatsApp webhook structure
            if 'entry' in payload:
                for entry in payload.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        if 'statuses' in value:
                            for status in value['statuses']:
                                if status.get('type') == 'payment':
                                    payment_data = status.get('payment', {})
                                    reference_id = payment_data.get('reference_id')
                                    if reference_id:
                                        return reference_id

            return ""
        except Exception as e:
            self.logger.error(f"Error extracting payment reference ID: {e}")
            return ""

    def _extract_payment_status(self, payload: Dict[str, Any]) -> str:
        """Extract payment status from webhook payload"""
        try:
            # Handle Meta/WhatsApp webhook structure
            if 'entry' in payload:
                for entry in payload.get('entry', []):
                    for change in entry.get('changes', []):
                        value = change.get('value', {})
                        if 'statuses' in value:
                            for status in value['statuses']:
                                if status.get('type') == 'payment':
                                    return status.get('status', 'unknown')

            return "unknown"
        except Exception as e:
            self.logger.error(f"Error extracting payment status: {e}")
            return "unknown"

    def _is_campaign_message(self, message_id: str) -> bool:
        """Check if message_id belongs to campaigns app"""
        try:
            from campaigns.models import Message
            return Message.objects.filter(message_id=message_id).exists()
        except Exception:
            return False

    def _is_order_message(self, message_id: str) -> bool:
        """Check if message_id belongs to orders app"""
        try:
            from orders.models import Order
            return Order.objects.filter(whatsapp_message_id=message_id).exists()
        except Exception:
            return False

    def route_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route webhook to appropriate processor

        Returns:
            Dict with 'success', 'processor_used', and 'result' keys
        """
        webhook_type = self.analyze_webhook_type(payload)

        self.logger.info(f"Routing webhook as type: {webhook_type}")

        try:
            if webhook_type == 'campaign_message_status':
                from campaigns.webhook_processor import process_360dialog_webhook
                result = process_360dialog_webhook(payload)
                return {
                    'success': result,
                    'processor_used': 'campaigns.webhook_processor.process_360dialog_webhook',
                    'webhook_type': webhook_type,
                    'result': result
                }

            elif webhook_type == 'order_message_status':
                # Create WebhookEvent record for orders app
                message_ids = self._extract_message_ids(payload)
                from orders.models import WebhookEvent
                webhook_event = WebhookEvent.objects.create(
                    event_type='message_status',
                    message_id=message_ids[0] if message_ids else '',
                    raw_data=payload,
                    processed=False
                )

                from orders.webhook_processor import process_order_webhook_status
                result = process_order_webhook_status(payload)

                # Update webhook event
                webhook_event.processed = result
                if result:
                    webhook_event.processed_at = timezone.now()
                    # Try to link to order
                    if message_ids:
                        try:
                            from orders.models import Order
                            order = Order.objects.get(whatsapp_message_id=message_ids[0])
                            webhook_event.order = order
                        except:
                            pass
                else:
                    webhook_event.processing_error = "Failed to process order message status webhook"
                webhook_event.save()

                return {
                    'success': result,
                    'processor_used': 'orders.webhook_processor.process_order_webhook_status',
                    'webhook_type': webhook_type,
                    'result': result,
                    'webhook_event_id': webhook_event.id
                }

            elif webhook_type == 'payment_status':
                # Create WebhookEvent record for orders app
                payment_reference_id = self._extract_payment_reference_id(payload)

                # Extract payment status for logging
                payment_status = self._extract_payment_status(payload)

                self.logger.info(f"🏦 Processing payment webhook: reference_id={payment_reference_id}, status={payment_status}")

                from orders.models import WebhookEvent
                webhook_event = WebhookEvent.objects.create(
                    event_type='payment_status',
                    payment_reference_id=payment_reference_id,
                    raw_data=payload,
                    processed=False
                )

                from orders.webhook_processor import process_payment_webhook
                result = process_payment_webhook(payload)

                # Update webhook event
                webhook_event.processed = result
                if result:
                    webhook_event.processed_at = timezone.now()
                    # Try to link to order
                    if payment_reference_id:
                        try:
                            from orders.models import Order
                            order = Order.objects.get(order_id=payment_reference_id)
                            webhook_event.order = order

                            # Log payment success message status
                            if payment_status == 'captured' and order.payment_success_message_sent:
                                self.logger.info(f"💬 Payment success message sent for order {payment_reference_id}: message_id={order.payment_success_message_id}")
                            elif payment_status == 'captured':
                                self.logger.warning(f"💬 Payment success message NOT sent for order {payment_reference_id}")

                        except Exception as e:
                            self.logger.warning(f"Could not link webhook to order {payment_reference_id}: {e}")
                else:
                    webhook_event.processing_error = "Failed to process payment webhook"
                webhook_event.save()

                return {
                    'success': result,
                    'processor_used': 'orders.webhook_processor.process_payment_webhook',
                    'webhook_type': webhook_type,
                    'result': result,
                    'webhook_event_id': webhook_event.id,
                    'payment_reference_id': payment_reference_id,
                    'payment_status': payment_status
                }

            else:
                self.logger.warning(f"No processor found for webhook type: {webhook_type}")
                return {
                    'success': False,
                    'processor_used': 'none',
                    'webhook_type': webhook_type,
                    'result': False,
                    'error': f'No processor for webhook type: {webhook_type}'
                }

        except Exception as e:
            self.logger.error(f"Error routing webhook: {e}")
            return {
                'success': False,
                'processor_used': 'error',
                'webhook_type': webhook_type,
                'result': False,
                'error': str(e)
            }


# Global router instance
webhook_router = UnifiedWebhookRouter()


def route_unified_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for webhook routing

    Args:
        payload: Raw webhook payload from 360dialog/WhatsApp

    Returns:
        Dict containing routing results
    """
    return webhook_router.route_webhook(payload)

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.views import View
from django.utils import timezone
import json
import logging
from .models import Message, Campaign, WebhookLog

logger = logging.getLogger(__name__)


class WhatsAppWebhookView(View):
    """Handle WhatsApp webhooks from 360dialog"""
    
    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def get(self, request):
        """
        Handle webhook verification (if 360dialog requires it)
        """
        # 360dialog might not require verification like Meta does
        # But we'll handle it just in case
        hub_mode = request.GET.get('hub.mode')
        hub_token = request.GET.get('hub.verify_token')
        hub_challenge = request.GET.get('hub.challenge')
        
        if hub_mode and hub_token:
            if hub_mode == 'subscribe' and hub_token == 'your_verify_token':
                logger.info("Webhook verified successfully")
                return HttpResponse(hub_challenge)
        
        return HttpResponse("OK")
    
    def post(self, request):
        """
        Handle webhook events from 360dialog
        """
        try:
            # Parse the webhook payload
            payload = json.loads(request.body)
            
            # Log the webhook for debugging
            webhook_log = WebhookLog.objects.create(
                event_type='360dialog_webhook',
                raw_payload=payload,
                processed=False
            )
            
            logger.info(f"Received webhook: {json.dumps(payload, indent=2)}")
            
            # Import task here to avoid circular import
            from .tasks import process_webhook_status
            
            # Process the webhook asynchronously
            process_webhook_status.delay(webhook_log.id)
            
            # Return immediate response to 360dialog
            return JsonResponse({'status': 'received'}, status=200)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}")
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return JsonResponse({'error': 'Internal error'}, status=500)
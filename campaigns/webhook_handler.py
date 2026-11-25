
import hashlib
import hmac

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.views import View
from django.utils import timezone
import json
import logging
from .models import Message, Campaign, WebhookLog

logger = logging.getLogger(__name__)


def _setting(name, default=''):
    return getattr(settings, name, default)


def authenticate_webhook(request):
    """Return None if the webhook may be processed, else (status_code, reason).

    360dialog offers two checks; every one that is configured must pass:
      WHATSAPP_WEBHOOK_SIGNING_SECRET  x-360dialog-signature = hex HMAC-SHA256(secret, raw body)
      WHATSAPP_WEBHOOK_AUTH_HEADER     exact Authorization header value, registered with
                                       360dialog in POST /v1/configs/webhook {"headers": {...}}
    With neither configured, webhooks are refused unless WHATSAPP_WEBHOOK_ALLOW_UNAUTHENTICATED
    is true (360dialog retries refused webhooks, so they arrive once auth is set up).
    """
    secret = _setting('WHATSAPP_WEBHOOK_SIGNING_SECRET')
    expected_auth = _setting('WHATSAPP_WEBHOOK_AUTH_HEADER')

    if not secret and not expected_auth:
        if _setting('WHATSAPP_WEBHOOK_ALLOW_UNAUTHENTICATED', False):
            return None
        return 401, 'webhook authentication is not configured'

    if expected_auth:
        given = request.headers.get('Authorization', '')
        if not hmac.compare_digest(given.encode(), expected_auth.encode()):
            return 401, 'missing or wrong Authorization header'

    if secret:
        given_sig = request.headers.get('X-360dialog-Signature', '')
        if not given_sig:
            return 401, 'missing x-360dialog-signature'
        expected_sig = hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(given_sig.strip().lower().encode(), expected_sig.encode()):
            return 403, 'x-360dialog-signature does not match'

    return None


class WhatsAppWebhookView(View):
    """Handle WhatsApp webhooks from 360dialog"""

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get(self, request):
        """Meta-style verification handshake (hub.mode=subscribe), checked against
        WHATSAPP_WEBHOOK_VERIFY_TOKEN. A plain GET (health check) just gets OK."""
        hub_mode = request.GET.get('hub.mode')
        hub_token = request.GET.get('hub.verify_token')
        hub_challenge = request.GET.get('hub.challenge', '')

        if hub_mode or hub_token:
            expected = _setting('WHATSAPP_WEBHOOK_VERIFY_TOKEN')
            if (hub_mode == 'subscribe' and expected and hub_token
                    and hmac.compare_digest(hub_token.encode(), expected.encode())):
                logger.info("Webhook verified successfully")
                return HttpResponse(hub_challenge, content_type='text/plain')
            logger.warning("Webhook verification refused: wrong or unconfigured verify token")
            return HttpResponse('Forbidden', status=403)

        return HttpResponse("OK")

    def post(self, request):
        """
        Handle webhook events from 360dialog
        """
        refused = authenticate_webhook(request)
        if refused:
            code, reason = refused
            logger.warning(f"Webhook refused ({code}): {reason}")
            return JsonResponse({'error': reason}, status=code)

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
            
            # Import unified router
            from .tasks import process_unified_webhook_status

            # Process the webhook asynchronously using unified router
            process_unified_webhook_status.delay(webhook_log.id)
            
            # Return immediate response to 360dialog
            return JsonResponse({'status': 'received'}, status=200)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook: {e}")
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return JsonResponse({'error': 'Internal error'}, status=500)
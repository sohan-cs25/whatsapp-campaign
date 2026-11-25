"""
Register the webhook URL with 360dialog, together with the Authorization header 360dialog
must send on every webhook (WHATSAPP_WEBHOOK_AUTH_HEADER), via POST /v1/configs/webhook.

    python manage.py configure_whatsapp_webhook --url https://<host>/webhook/whatsapp/          # dry run
    python manage.py configure_whatsapp_webhook --url https://<host>/webhook/whatsapp/ --apply  # do it

Make a header value once, put it in .env as WHATSAPP_WEBHOOK_AUTH_HEADER, deploy, then run this:
    python -c "import secrets; print('Bearer ' + secrets.token_urlsafe(32))"
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Register the webhook URL and its Authorization header with 360dialog."

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True, help="Public HTTPS webhook URL, e.g. https://host/webhook/whatsapp/")
        parser.add_argument("--apply", action="store_true", help="Send the change to 360dialog (default: dry run)")

    def handle(self, *args, url, apply, **opts):
        if not url.startswith("https://"):
            raise CommandError("360dialog only delivers to HTTPS URLs")
        auth = getattr(settings, "WHATSAPP_WEBHOOK_AUTH_HEADER", "")
        if not auth:
            raise CommandError("Set WHATSAPP_WEBHOOK_AUTH_HEADER first (see this command's help)")
        cfg = getattr(settings, "WHATSAPP_CONFIG", {})
        api_url = (cfg.get("API_URL") or "https://waba-v2.360dialog.io").rstrip("/")
        endpoint = f"{api_url}/v1/configs/webhook"
        masked = auth[:10] + "…"

        if not apply:
            self.stdout.write(f"Dry run: would POST {endpoint}\n  url: {url}\n  Authorization: {masked}\n"
                              "Run again with --apply to send it.")
            return

        if not cfg.get("API_KEY"):
            raise CommandError("WHATSAPP_360_API_KEY is not set")
        resp = requests.post(endpoint, headers={"D360-API-KEY": cfg["API_KEY"], "Content-Type": "application/json"},
                             json={"url": url, "headers": {"Authorization": auth}}, timeout=30)
        if resp.status_code not in (200, 201):
            raise CommandError(f"360dialog answered {resp.status_code}: {resp.text[:300]}")
        self.stdout.write(self.style.SUCCESS(f"Webhook set to {url} with Authorization {masked}"))

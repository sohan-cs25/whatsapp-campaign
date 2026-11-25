"""Campaign sending must deliver each message at most once."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APITestCase

from campaigns.models import Campaign, Message
from campaigns import tasks

OK = {"success": True, "message_id": "wamid.1", "response": {}, "status_code": 200}


def make_campaign(status="running", n=1, user=None):
    user = user or User.objects.create_user("marketer", password="x")
    c = Campaign.objects.create(user=user, template_name="promo", total_recipients=n, status=status)
    msgs = [Message.objects.create(campaign=c, phone_number=f"91980000000{i}") for i in range(n)]
    return c, msgs


class SendOnceTests(TestCase):
    def setUp(self):
        p = patch("campaigns.tasks.WhatsApp360Client")
        self.client_cls = p.start()
        self.addCleanup(p.stop)
        self.send = self.client_cls.return_value.send_template_message
        self.send.return_value = OK
        p2 = patch("campaigns.tasks.check_campaign_completion")
        p2.start()
        self.addCleanup(p2.stop)

    def test_two_tasks_for_same_message_send_once(self):
        """A second task for the same message (scheduled + webhook-triggered, or a resume)
        starting while the first is still before its send must not send again."""
        _, (msg,) = make_campaign()
        state = {"inner_ran": False}

        def concurrent_task(_seconds):
            if not state["inner_ran"]:
                state["inner_ran"] = True
                tasks.send_whatsapp_message(msg.id)

        with patch("campaigns.tasks.time.sleep", side_effect=concurrent_task):
            tasks.send_whatsapp_message(msg.id)
        assert self.send.call_count == 1
        msg.refresh_from_db()
        assert msg.status == "sent"

    def test_paused_campaign_does_not_send(self):
        _, (msg,) = make_campaign(status="paused")
        with patch("campaigns.tasks.time.sleep"):
            tasks.send_whatsapp_message(msg.id)
        self.send.assert_not_called()
        msg.refresh_from_db()
        assert msg.status == "queued"  # resume sends it later

    def test_sent_counter_counts_once(self):
        c, (msg,) = make_campaign()
        with patch("campaigns.tasks.time.sleep"):
            tasks.send_whatsapp_message(msg.id)
            tasks.send_whatsapp_message(msg.id)
        c.refresh_from_db()
        assert c.sent_count == 1 and self.send.call_count == 1


class DeliveredWebhookTests(TestCase):
    def test_delivered_does_not_trigger_another_send(self):
        """Messages are pre-scheduled by start_campaign_task; a delivery receipt must not
        send the next queued message early (it is already scheduled)."""
        from campaigns.webhook_processor import process_campaign_webhook_status
        c, (first, _second) = make_campaign(n=2)
        Message.objects.filter(id=first.id).update(status="sent", message_id="wamid.1")
        first.refresh_from_db()
        with patch("campaigns.tasks.send_next_message") as nxt, \
                patch("campaigns.tasks.send_whatsapp_message") as snd:
            process_campaign_webhook_status({}, {"id": "wamid.1", "status": "delivered"}, first)
        nxt.delay.assert_not_called()
        snd.delay.assert_not_called()
        first.refresh_from_db(); c.refresh_from_db()
        assert first.status == "delivered" and c.delivered_count == 1


class StartResumeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user("marketer", password="x")
        self.client.force_authenticate(self.user)

    def assert_running_before_scheduling(self, action, start_status):
        c, _ = make_campaign(status=start_status, user=self.user)
        seen = []
        with patch("campaigns.tasks.start_campaign_task") as task:
            task.delay.side_effect = lambda cid: seen.append(Campaign.objects.get(id=cid).status)
            r = self.client.post(f"/api/campaigns/{c.id}/{action}/")
            r2 = self.client.post(f"/api/campaigns/{c.id}/{action}/")
        assert r.status_code == 200 and r2.status_code == 400
        assert seen == ["running"], seen

    def test_start_marks_running_before_scheduling_and_only_once(self):
        self.assert_running_before_scheduling("start", "pending")

    def test_resume_marks_running_before_scheduling_and_only_once(self):
        self.assert_running_before_scheduling("resume", "paused")


REJECTED = {"success": False, "error": "(#131026) Message undeliverable", "status_code": 400, "rejected": True}
TIMEOUT = {"success": False, "error": "Request timeout", "status_code": 408}


class RetryOnceTests(TestCase):
    """A message 360dialog rejected is retried once; anything where the message may have
    gone out (timeout, network error) is not retried, to avoid duplicates."""

    def setUp(self):
        p = patch("campaigns.tasks.WhatsApp360Client")
        self.send = p.start().return_value.send_template_message
        self.addCleanup(p.stop)
        for target in ("campaigns.tasks.check_campaign_completion", "campaigns.tasks.time.sleep"):
            q = patch(target)
            q.start()
            self.addCleanup(q.stop)
        self.campaign, (self.msg,) = make_campaign()

    def run_task(self):
        """Run one attempt; returns True if it asked Celery for a retry."""
        from celery.exceptions import Retry
        with patch.object(tasks.send_whatsapp_message, "retry", side_effect=Retry()) as retry:
            try:
                tasks.send_whatsapp_message(self.msg.id)
            except Retry:
                pass
        self.msg.refresh_from_db()
        self.retry_calls = retry.call_count
        return retry.call_count > 0

    def test_rejected_then_ok_sends_on_retry(self):
        self.send.side_effect = [REJECTED, OK]
        assert self.run_task() and self.retry_calls == 1
        assert self.msg.status == "queued" and self.msg.retry_count == 1
        assert not self.run_task()
        self.campaign.refresh_from_db()
        assert self.msg.status == "sent" and self.send.call_count == 2 and self.campaign.sent_count == 1

    def test_rejected_twice_fails_without_third_attempt(self):
        self.send.return_value = REJECTED
        assert self.run_task()
        assert not self.run_task()
        assert self.msg.status == "failed" and self.msg.retry_count == 2
        assert self.msg.error_message == REJECTED["error"]
        assert not self.run_task()  # a stray extra task does nothing
        assert self.send.call_count == 2

    def test_timeout_is_not_retried(self):
        self.send.return_value = TIMEOUT
        assert not self.run_task()
        assert self.msg.status == "failed" and self.send.call_count == 1


class ClientRejectedFlagTests(TestCase):
    def make_client(self):
        from campaigns.whatsapp_360_client import WhatsApp360Client
        with patch("campaigns.whatsapp_360_client.config", return_value="k"):
            return WhatsApp360Client()

    def test_http_error_response_is_rejected(self):
        c = self.make_client()
        resp = type("R", (), {"status_code": 400, "json": lambda self: {"error": {"message": "bad"}},
                              "text": "bad"})()
        with patch.object(c.session, "post", return_value=resp):
            r = c.send_template_message("919800000001", "promo")
        assert r["success"] is False and r.get("rejected") is True

    def test_timeout_is_not_rejected(self):
        import requests
        c = self.make_client()
        with patch.object(c.session, "post", side_effect=requests.exceptions.Timeout()):
            r = c.send_template_message("919800000001", "promo")
        assert r["success"] is False and not r.get("rejected")


import hashlib
import hmac
import json as _json

from django.test import override_settings

WEBHOOK_URLS = ["/webhook/whatsapp/", "/api/webhook/whatsapp/"]
BODY = _json.dumps({"statuses": [{"id": "wamid.1", "status": "delivered"}]}).encode()


def signature(secret, body=BODY):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@override_settings(WHATSAPP_WEBHOOK_SIGNING_SECRET="", WHATSAPP_WEBHOOK_AUTH_HEADER="",
                   WHATSAPP_WEBHOOK_ALLOW_UNAUTHENTICATED=False, WHATSAPP_WEBHOOK_VERIFY_TOKEN="")
class WebhookAuthTests(TestCase):
    def setUp(self):
        p = patch("campaigns.tasks.process_unified_webhook_status")
        self.task = p.start()
        self.addCleanup(p.stop)

    def post(self, url=WEBHOOK_URLS[0], body=BODY, **headers):
        return self.client.post(url, data=body, content_type="application/json", **headers)

    def assert_rejected(self, response, code):
        from campaigns.models import WebhookLog
        assert response.status_code == code, response.status_code
        self.task.delay.assert_not_called()
        assert not WebhookLog.objects.exists()

    # signature (x-360dialog-signature)
    @override_settings(WHATSAPP_WEBHOOK_SIGNING_SECRET="s3cret")
    def test_valid_signature_accepted_on_both_urls(self):
        for url in WEBHOOK_URLS:
            r = self.post(url, HTTP_X_360DIALOG_SIGNATURE=signature("s3cret"))
            assert r.status_code == 200, (url, r.status_code)
        assert self.task.delay.call_count == 2

    @override_settings(WHATSAPP_WEBHOOK_SIGNING_SECRET="s3cret")
    def test_missing_signature_401(self):
        self.assert_rejected(self.post(), 401)

    @override_settings(WHATSAPP_WEBHOOK_SIGNING_SECRET="s3cret")
    def test_wrong_signature_403(self):
        self.assert_rejected(self.post(HTTP_X_360DIALOG_SIGNATURE=signature("other")), 403)

    @override_settings(WHATSAPP_WEBHOOK_SIGNING_SECRET="s3cret")
    def test_signature_of_different_body_403(self):
        sig = signature("s3cret")
        self.assert_rejected(self.post(body=BODY.replace(b"delivered", b"read"), HTTP_X_360DIALOG_SIGNATURE=sig), 403)

    # shared header (set with POST /v1/configs/webhook "headers")
    @override_settings(WHATSAPP_WEBHOOK_AUTH_HEADER="Basic dXNlcjpwYXNz")
    def test_auth_header_accepted(self):
        assert self.post(HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz").status_code == 200

    @override_settings(WHATSAPP_WEBHOOK_AUTH_HEADER="Basic dXNlcjpwYXNz")
    def test_wrong_auth_header_401(self):
        self.assert_rejected(self.post(HTTP_AUTHORIZATION="Basic d3Jvbmc="), 401)

    @override_settings(WHATSAPP_WEBHOOK_AUTH_HEADER="Basic dXNlcjpwYXNz", WHATSAPP_WEBHOOK_SIGNING_SECRET="s3cret")
    def test_both_configured_both_required(self):
        self.assert_rejected(self.post(HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz"), 401)
        r = self.post(HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz", HTTP_X_360DIALOG_SIGNATURE=signature("s3cret"))
        assert r.status_code == 200

    # nothing configured
    def test_unconfigured_rejects_by_default(self):
        self.assert_rejected(self.post(), 401)

    @override_settings(WHATSAPP_WEBHOOK_ALLOW_UNAUTHENTICATED=True)
    def test_unconfigured_allowed_only_when_opted_in(self):
        assert self.post().status_code == 200

    # GET verification handshake
    @override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN="tok-123")
    def test_verify_token_echoes_challenge(self):
        r = self.client.get(WEBHOOK_URLS[0], {"hub.mode": "subscribe", "hub.verify_token": "tok-123",
                                              "hub.challenge": "42"})
        assert r.status_code == 200 and r.content == b"42"

    @override_settings(WHATSAPP_WEBHOOK_VERIFY_TOKEN="tok-123")
    def test_wrong_verify_token_403(self):
        r = self.client.get(WEBHOOK_URLS[0], {"hub.mode": "subscribe", "hub.verify_token": "your_verify_token",
                                              "hub.challenge": "42"})
        assert r.status_code == 403 and b"42" not in r.content

    def test_old_hardcoded_token_no_longer_works(self):
        r = self.client.get(WEBHOOK_URLS[0], {"hub.mode": "subscribe", "hub.verify_token": "your_verify_token",
                                              "hub.challenge": "42"})
        assert r.status_code == 403

    def test_plain_get_still_ok(self):
        assert self.client.get(WEBHOOK_URLS[0]).status_code == 200


from io import StringIO

from django.core.management import CommandError, call_command

AUTH = "Bearer abcdefghijklmnopqrstuvwxyz0123456789"


@override_settings(WHATSAPP_WEBHOOK_AUTH_HEADER=AUTH,
                   WHATSAPP_CONFIG={"API_KEY": "d360-key", "API_URL": "https://waba-v2.360dialog.io"})
class ConfigureWebhookCommandTests(TestCase):
    def run_cmd(self, *args):
        out = StringIO()
        call_command("configure_whatsapp_webhook", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_does_not_call_360dialog(self):
        with patch("campaigns.management.commands.configure_whatsapp_webhook.requests.post") as post:
            out = self.run_cmd("--url", "https://example.com/webhook/whatsapp/")
        post.assert_not_called()
        assert "--apply" in out and AUTH not in out  # never print the secret

    def test_apply_registers_url_and_header(self):
        with patch("campaigns.management.commands.configure_whatsapp_webhook.requests.post") as post:
            post.return_value.status_code = 201
            post.return_value.json.return_value = {"url": "https://example.com/webhook/whatsapp/"}
            out = self.run_cmd("--url", "https://example.com/webhook/whatsapp/", "--apply")
        url, = post.call_args.args
        assert url == "https://waba-v2.360dialog.io/v1/configs/webhook"
        assert post.call_args.kwargs["headers"]["D360-API-KEY"] == "d360-key"
        assert post.call_args.kwargs["json"] == {"url": "https://example.com/webhook/whatsapp/",
                                                 "headers": {"Authorization": AUTH}}
        assert AUTH not in out

    def test_refuses_without_auth_header_setting(self):
        with override_settings(WHATSAPP_WEBHOOK_AUTH_HEADER=""), self.assertRaises(CommandError):
            self.run_cmd("--url", "https://example.com/webhook/whatsapp/", "--apply")

    def test_refuses_non_https_url(self):
        with self.assertRaises(CommandError):
            self.run_cmd("--url", "http://example.com/webhook/whatsapp/", "--apply")

    def test_api_error_is_reported(self):
        with patch("campaigns.management.commands.configure_whatsapp_webhook.requests.post") as post:
            post.return_value.status_code = 401
            post.return_value.text = "unauthorized"
            with self.assertRaises(CommandError):
                self.run_cmd("--url", "https://example.com/webhook/whatsapp/", "--apply")

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

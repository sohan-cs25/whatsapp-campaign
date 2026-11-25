"""Legacy validated-file send: queued in the background (no request timeout), each order sent once."""

from unittest.mock import patch

from rest_framework.test import APITestCase

from orders.models import Order, ValidatedFile
from orders.tests.helpers import make_user

URL = "/api/orders/send-messages/"


class LegacySendTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.vf = ValidatedFile.objects.create(user=self.user, file_name="validated.xlsx",
                                               filepath="validatedchatfile/validated.xlsx", filetype="xlsx",
                                               is_processed=True)
        # Orders created before the review redesign have review_status 'draft' unless backfilled.
        self.orders = [Order.objects.create(user=self.user, validated_file=self.vf, number=f"91980000000{i}",
                                            order_items="Apples:2", amount="100=100", review_status=rs)
                       for i, rs in enumerate(["approved", "draft"])]
        Order.objects.create(user=self.user, validated_file=self.vf, number="919800000009",
                             order_items="Apples:2", amount="100=100", status="sent", review_status="approved")
        p = patch("campaigns.whatsapp_360_client.WhatsApp360Client")
        self.wa = p.start().return_value
        self.addCleanup(p.stop)
        self.wa.send_message.return_value = {"success": True, "message_id": "wamid.x", "status_code": 200}

    def post(self, file_id=None):
        return self.client.post(URL, {"validated_file_id": str(file_id or self.vf.id)}, format="json")

    def test_returns_immediately_with_queued_count(self):
        with patch("orders.views.send_validated_file_orders") as task, \
                patch("orders.whatsapp_service.OrderWhatsAppService.send_order_message") as send_now:
            r = self.post()
        assert r.status_code == 202, r.data
        assert r.data["queued"] == 2 and r.data["success"] is True
        task.delay.assert_called_once_with(str(self.vf.id))
        send_now.assert_not_called()

    def test_queued_orders_are_sent_including_unbackfilled_drafts(self):
        r = self.post()  # Celery runs eagerly in tests
        assert r.status_code == 202
        statuses = sorted(Order.objects.filter(validated_file=self.vf).values_list("status", flat=True))
        assert statuses == ["sent", "sent", "sent"]
        assert self.wa.send_message.call_count == 2

    def test_second_click_does_not_resend(self):
        self.post()
        r = self.post()
        assert r.status_code == 400  # nothing pending any more
        assert self.wa.send_message.call_count == 2

    def test_task_twice_sends_each_order_once(self):
        from orders.tasks import send_validated_file_orders
        Order.objects.filter(validated_file=self.vf).update(review_status="approved")
        send_validated_file_orders(str(self.vf.id))
        send_validated_file_orders(str(self.vf.id))
        assert self.wa.send_message.call_count == 2

    def test_other_users_file_is_404(self):
        self.client.force_authenticate(make_user("other"))
        assert self.post().status_code == 404
        assert self.wa.send_message.call_count == 0

from decimal import Decimal as D
from unittest.mock import patch

from rest_framework.test import APITestCase

from orders.models import Order
from orders.tests.helpers import add_line, make_parsed_file, make_products, make_user


class ReviewApiTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.pf = make_parsed_file(self.user)
        self.mango, self.lychee = make_products()
        self.clean = self.make_order("Asha", "919800000001", needs_review=False)
        self.blocked = self.make_order("Ravi", "", needs_review=True)

    def make_order(self, name, number, needs_review, status="pending"):
        o = Order.objects.create(user=self.user, parsed_file=self.pf, customer_name=name, number=number,
                                 order_items="", amount="", needs_review=needs_review, status=status)
        add_line(o, self.mango, D("1"), "kg")
        o.refresh_totals()
        return o

    def url(self, suffix=""):
        return f"/api/orders/review/{self.pf.id}/{suffix}"

    def patch_order(self, order, body):
        return self.client.patch(f"/api/orders/review/orders/{order.id}/", body, format="json")

    def test_list_sorts_flagged_first(self):
        r = self.client.get(self.url())
        assert r.status_code == 200
        assert [o["customer_name"] for o in r.data["orders"]] == ["Ravi", "Asha"]
        assert r.data["summary"]["orders"] == 2 and r.data["summary"]["needs_review"] == 1
        assert r.data["summary"]["total_paise"] == 24000
        assert r.data["orders"][0]["blocking_issues"] == ["no_phone"]
        assert r.data["orders"][0]["lines"][0]["product"] == "kesar_mango"

    def test_other_users_file_is_404(self):
        self.client.force_authenticate(make_user("other"))
        assert self.client.get(self.url()).status_code == 404
        assert self.patch_order(self.clean, {"address": "X"}).status_code == 404

    def test_patch_lines_reprices(self):
        r = self.patch_order(self.clean, {"lines": [{"product": "kesar_mango", "name": "Kesar Mango",
                                                     "quantity": "2", "unit": "kg"}]})
        assert r.status_code == 200, r.data
        assert r.data["lines"][0]["line_total_paise"] == 24000 and r.data["total_paise"] == 24000

    def test_patch_phone_clears_needs_review(self):
        r = self.patch_order(self.blocked, {"number": "919800000002"})
        assert r.status_code == 200 and r.data["needs_review"] is False and r.data["blocking_issues"] == []

    def test_patch_sent_order_409(self):
        sent = self.make_order("Sent", "919800000003", False, status="sent")
        r = self.patch_order(sent, {"address": "C-1"})
        assert r.status_code == 409 and r.data == {"error": "Order already sent"}

    def test_patch_unknown_product_400(self):
        r = self.patch_order(self.clean, {"lines": [{"product": "nope", "name": "x", "quantity": "1", "unit": "kg"}]})
        assert r.status_code == 400

    def test_patch_cannot_approve_directly(self):
        assert self.patch_order(self.clean, {"review_status": "approved"}).status_code == 400

    def test_approve_refuses_blocked(self):
        r = self.client.post(self.url("approve/"), {"order_ids": [str(self.blocked.id), str(self.clean.id)]},
                             format="json")
        assert r.status_code == 200
        assert r.data["approved"] == [str(self.clean.id)]
        assert r.data["refused"] == [{"id": str(self.blocked.id), "issues": ["no_phone"]}]

    def test_approve_all_clean(self):
        r = self.client.post(self.url("approve/"), {"all_clean": True}, format="json")
        assert r.data["approved"] == [str(self.clean.id)]
        self.clean.refresh_from_db()
        self.blocked.refresh_from_db()
        assert self.clean.review_status == "approved" and self.blocked.review_status == "draft"

    def test_send_without_approved_400(self):
        assert self.client.post(self.url("send/")).status_code == 400

    @patch("orders.review_views.send_order_batch")
    def test_send_queues_batch(self, batch):
        Order.objects.filter(pk=self.clean.pk).update(review_status="approved")
        r = self.client.post(self.url("send/"))
        assert r.status_code == 200 and r.data == {"queued": 1}
        batch.delay.assert_called_once_with(str(self.pf.id))

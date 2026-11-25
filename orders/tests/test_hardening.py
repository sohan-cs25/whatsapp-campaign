"""Follow-up fixes after the review redesign: stuck sends, bad input, product permissions,
price-unit changes after pricing."""

from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from orders.models import Order, Product
from orders.tests.helpers import add_line, make_parsed_file, make_products, make_user


def approved_order(user, pf, product, qty="1", unit="kg", status="pending"):
    o = Order.objects.create(user=user, parsed_file=pf, customer_name="Asha", number="919800000001",
                             order_items="", amount="", review_status="approved", status=status)
    add_line(o, product, D(qty), unit)
    o.refresh_totals()
    return o


class StuckSendingTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.pf = make_parsed_file(self.user)
        self.mango, _ = make_products()

    def test_send_error_before_service_marks_failed(self):
        from orders.tasks import send_single_order
        o = approved_order(self.user, self.pf, self.mango)
        with patch("orders.whatsapp_service.OrderWhatsAppService", side_effect=RuntimeError("no api key")):
            assert send_single_order(str(o.id)) == "failed"
        o.refresh_from_db()
        assert o.status == "failed" and "no api key" in o.whatsapp_response_json["error"]

    def test_claim_refreshes_updated_at(self):
        from orders.tasks import send_single_order
        o = approved_order(self.user, self.pf, self.mango)
        Order.objects.filter(id=o.id).update(updated_at=timezone.now() - timedelta(hours=2))
        seen = {}

        def fake_send(order):
            seen["updated_at"] = Order.objects.get(id=order.id).updated_at

        with patch("orders.whatsapp_service.OrderWhatsAppService") as svc:
            svc.return_value.send_order_message.side_effect = fake_send
            send_single_order(str(o.id))
        assert timezone.now() - seen["updated_at"] < timedelta(minutes=1)

    def test_sweep_fails_only_stale_sending_orders(self):
        from orders.tasks import fail_stuck_sending_orders
        stale = approved_order(self.user, self.pf, self.mango, status="sending")
        fresh = approved_order(self.user, self.pf, self.mango, status="sending")
        Order.objects.filter(id=stale.id).update(updated_at=timezone.now() - timedelta(minutes=20))
        assert fail_stuck_sending_orders() == 1
        stale.refresh_from_db(); fresh.refresh_from_db()
        assert stale.status == "failed" and "interrupted" in stale.whatsapp_response_json["error"]
        assert fresh.status == "sending"

    def test_sweep_is_scheduled(self):
        tasks = [e["task"] for e in settings.CELERY_BEAT_SCHEDULE.values()]
        assert "orders.tasks.fail_stuck_sending_orders" in tasks


class ReviewInputTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.pf = make_parsed_file(self.user)
        self.mango, _ = make_products()
        self.order = Order.objects.create(user=self.user, parsed_file=self.pf, number="919800000001",
                                          order_items="", amount="")

    def test_approve_malformed_id_is_400(self):
        r = self.client.post(f"/api/orders/review/{self.pf.id}/approve/", {"order_ids": ["not-a-uuid"]},
                             format="json")
        assert r.status_code == 400

    def test_negative_quantity_is_400(self):
        r = self.client.patch(f"/api/orders/review/orders/{self.order.id}/", {"lines": [
            {"product": "kesar_mango", "name": "Kesar Mango", "quantity": "-1", "unit": "kg"}]}, format="json")
        assert r.status_code == 400 and "lines" in r.data

    def test_zero_quantity_is_400(self):
        r = self.client.patch(f"/api/orders/review/orders/{self.order.id}/", {"lines": [
            {"product": "kesar_mango", "name": "Kesar Mango", "quantity": "0", "unit": "kg"}]}, format="json")
        assert r.status_code == 400


class ProductPermissionTests(APITestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_authenticate(self.user)
        self.mango, _ = make_products()
        self.url = f"/api/orders/products/{self.mango.id}/"

    def test_plain_user_can_read(self):
        assert self.client.get("/api/orders/products/").status_code == 200

    def test_plain_user_cannot_write(self):
        assert self.client.patch(self.url, {"price": "1"}, format="json").status_code == 403
        assert self.client.delete(self.url).status_code == 403
        assert self.client.post("/api/orders/products/", {"key": "x", "name": "X", "price": "1",
                                                          "price_unit": "kg"}, format="json").status_code == 403
        self.mango.refresh_from_db()
        assert self.mango.price == D("120") and self.mango.is_active

    def test_user_with_change_permission_can_edit(self):
        self.user.user_permissions.add(Permission.objects.get(codename="change_product"))
        assert self.client.patch(self.url, {"price": "130"}, format="json").status_code == 200


class PriceUnitChangeTests(TestCase):
    def test_items_still_sum_after_price_unit_change(self):
        from orders.whatsapp_service import OrderWhatsAppService
        user = make_user()
        mango, _ = make_products()
        o = approved_order(user, make_parsed_file(user), mango, qty="500", unit="g")  # 0.5 kg x 120 = 6000
        Product.objects.filter(id=mango.id).update(price_unit="g")
        o = Order.objects.get(id=o.id)
        items = [OrderWhatsAppService.line_to_whatsapp_item(l) for l in o.lines.all()]
        assert sum(i["quantity"] * i["amount"]["value"] for i in items) == o.total_paise == 6000


class ProductRowChangedTests(TestCase):
    def test_numeric_price_formats_compare_equal(self):
        from orders_streamlit.product_rows import product_row_changed
        old = {"key": "kesar_mango", "name": "Kesar Mango", "price": "120.00", "price_unit": "kg", "is_active": True}
        same = {"key": "kesar_mango", "name": "Kesar Mango", "price": "120.0", "price_unit": "kg", "is_active": True}
        assert not product_row_changed(old, same)
        assert product_row_changed(old, dict(same, price="125.0"))
        assert product_row_changed(old, dict(same, is_active=False))
        assert product_row_changed(old, dict(same, name="Kesar"))

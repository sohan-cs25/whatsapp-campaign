from decimal import Decimal as D
from unittest.mock import patch

from django.test import TestCase

from orders.models import Order
from orders.tests.helpers import add_line, make_parsed_file, make_products, make_user


def details(payload):
    return payload["template"]["components"][0]["parameters"][0]["action"]["order_details"]


class SendingTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.pf = make_parsed_file(self.user)
        self.mango, self.lychee = make_products()
        patcher = patch("campaigns.whatsapp_360_client.WhatsApp360Client")
        self.client_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.client_cls.return_value.send_message.return_value = {
            "success": True, "message_id": "wamid.x", "status_code": 200}

    def order(self, review_status="approved", lines=(("mango", "1", "kg"),)):
        o = Order.objects.create(user=self.user, parsed_file=self.pf, number="919800000001", order_items="",
                                 amount="", review_status=review_status)
        for which, qty, unit in lines:
            add_line(o, self.mango if which == "mango" else self.lychee, D(qty), unit)
        o.refresh_totals()
        return o

    def payload(self, order):
        from orders.whatsapp_service import OrderWhatsAppService
        return OrderWhatsAppService().build_order_details_payload(order)

    def test_items_sum_to_total_fractional(self):
        o = self.order(lines=(("mango", "0.5", "kg"), ("mango", "250", "g"), ("lychee", "2", "box")))
        d = details(self.payload(o))
        items = d["order"]["items"]
        assert sum(i["quantity"] * i["amount"]["value"] for i in items) == o.total_paise == 59000
        assert d["order"]["subtotal"]["value"] == d["total_amount"]["value"] == 59000
        assert items[0]["name"] == "Kesar Mango (0.5 kg)" and items[0]["quantity"] == 1
        assert items[1]["name"] == "Kesar Mango (250 g)" and items[1]["amount"]["value"] == 3000

    def test_whole_quantity_uses_unit_price(self):
        item = details(self.payload(self.order(lines=(("lychee", "2", "box"),))))["order"]["items"][0]
        assert item["quantity"] == 2 and item["amount"] == {"offset": 100, "value": 25000}
        assert item["name"] == "Lychee" and item["importer_name"] == "Farmveda"

    def test_reference_id_is_order_id(self):
        o = self.order()
        assert details(self.payload(o))["reference_id"] == o.order_id

    def test_legacy_order_without_lines_unchanged(self):
        o = Order.objects.create(user=self.user, number="919800000001", order_items="Apples:2", amount="100=100",
                                 review_status="approved")
        d = details(self.payload(o))
        assert len(d["order"]["items"]) == 1 and d["total_amount"]["value"] == 10000

    def test_send_single_order_once(self):
        from orders.tasks import send_single_order
        o = self.order()
        assert send_single_order(str(o.id)) == "sent"
        assert send_single_order(str(o.id)) == "skipped"
        assert self.client_cls.return_value.send_message.call_count == 1

    def test_rejected_order_not_sent(self):
        from orders.tasks import send_single_order
        o = self.order(review_status="rejected")
        assert send_single_order(str(o.id)) == "skipped"
        self.client_cls.return_value.send_message.assert_not_called()

    def test_batch_schedules_with_2s_gap(self):
        from orders.tasks import send_order_batch
        orders = [self.order() for _ in range(3)]
        self.order(review_status="draft")
        with patch("orders.tasks.send_single_order.apply_async") as apply_async:
            assert send_order_batch(str(self.pf.id)) == {"scheduled": 3}
        calls = [(c.kwargs["args"], c.kwargs["countdown"]) for c in apply_async.call_args_list]
        assert calls == [([str(o.id)], i * 2) for i, o in enumerate(orders)]

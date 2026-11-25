import os
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.conf import settings
from django.test import TestCase

from orders.models import ChatFile, Order, ParsedChatFile
from orders.order_builder import RebuildBlocked, build_orders
from orders.tests.helpers import make_parsed_file, make_products, make_user


def row(sender="919800000001", product="Kesar Mango", product_id="kesar_mango", base_qty=1000.0,
        base_unit="g", kind="new", flags="", needs_review=False, address="C-710", phone=None, mid="m1"):
    return {"date": "1/6/26", "time": "9:00 am", "sender": sender, "address": address, "phone": phone,
            "product": product, "product_id": product_id, "in_catalog": product_id is not None,
            "as_written": product, "quantity": None, "unit": None, "base_qty": base_qty, "base_unit": base_unit,
            "kind": kind, "message_ids": mid, "flags": flags, "needs_review": needs_review}


class BuildOrdersTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.pf = make_parsed_file(self.user)
        self.mango, self.lychee = make_products()

    def build(self, rows):
        return build_orders(self.pf, pd.DataFrame(rows))

    def test_addition_merges_into_one_order(self):
        orders = self.build([row(), row(base_qty=500.0, kind="addition", mid="m2")])
        assert len(orders) == 1
        lines = list(orders[0].lines.all())
        assert len(lines) == 1 and lines[0].quantity == 1500 and lines[0].unit == "g"
        assert orders[0].total_paise == 18000
        assert orders[0].customer_name == "919800000001" and orders[0].number == "919800000001"
        assert orders[0].address == "C-710" and orders[0].review_status == "draft"
        assert orders[0].user == self.user and orders[0].parsed_file == self.pf

    def test_cancellation_subtracts(self):
        orders = self.build([row(), row(base_qty=-1000.0, kind="cancellation", mid="m2"),
                             row(product="Lychee", product_id="lychee", base_qty=1.0, base_unit="box", mid="m3")])
        lines = list(orders[0].lines.all())
        assert [l.name for l in lines] == ["Lychee"]
        assert "had_cancellation" in orders[0].review_flags

    def test_fully_cancelled_customer_is_skipped(self):
        assert self.build([row(), row(base_qty=-1000.0, kind="cancellation", mid="m2")]) == []

    def test_name_sender_without_phone(self):
        order = self.build([row(sender="Ravi")])[0]
        assert order.number == "" and "no_phone" in order.blocking_issues() and order.needs_review

    def test_name_sender_with_phone_column(self):
        assert self.build([row(sender="Ravi", phone="98000 00002")])[0].number == "919800000002"

    def test_unknown_product_needs_review(self):
        order = self.build([row(product="Jackfruit", product_id=None, base_qty=1.0, base_unit="piece")])[0]
        line = order.lines.get()
        assert line.product is None and "unknown_product" in line.flags and order.needs_review

    def test_clean_order_does_not_need_review(self):
        order = self.build([row(flags="address_from_other_orders")])[0]
        assert order.needs_review is False

    def test_missing_quantity_line(self):
        order = self.build([row(base_qty=None, flags="missing_quantity", needs_review=True)])[0]
        line = order.lines.get()
        assert line.quantity is None and "missing_quantity" in line.flags and order.needs_review

    def test_itemless_cancellation_kept(self):
        order = self.build([row(product=None, product_id=None, base_qty=None, base_unit=None,
                                kind="cancellation", flags="no_items", needs_review=True)])[0]
        assert "cancellation_without_items" in order.review_flags and order.lines.count() == 0

    def test_rebuild_replaces_drafts(self):
        self.build([row()])
        self.build([row()])
        assert Order.objects.filter(parsed_file=self.pf).count() == 1

    def test_rebuild_blocked_after_approval(self):
        Order.objects.filter(pk=self.build([row()])[0].pk).update(review_status="approved")
        with self.assertRaises(RebuildBlocked):
            self.build([row()])


class ProcessChatFileTests(TestCase):
    def test_process_chat_file_creates_orders(self):
        from orders.tasks import process_chat_file
        user = make_user()
        make_products()
        rel = "chatfile/test_builder_chat.txt"
        path = os.path.join(settings.ORDERS_MEDIA_ROOT, rel)
        with open(path, "w", encoding="utf-8") as f:
            f.write("01/06/2026, 9:05 am - +91 98000 00001: 1 kg kesar C710\n")
        self.addCleanup(os.remove, path)
        chat = ChatFile.objects.create(user=user, filename="test_builder_chat.txt", filepath=rel, filetype="text")
        stats = SimpleNamespace(total_messages=1, orders_found=1, message_types={}, processing_time=0.1,
                                success_rate=1.0)
        fake = (lambda messages, chat_file_id: ([dict(m, Message_Type="order", Items="", Total_Amount="")
                                                 for m in messages], stats, {"orders": pd.DataFrame([row()])}))
        with patch("orders.ai_service.django_ai_service.process_chat_messages_sync", side_effect=fake), \
             patch("orders.tasks.save_enhanced_messages_to_excel", return_value=True):
            result = process_chat_file.apply(args=[str(chat.id)]).get()
        assert result["success"], result
        pf = ParsedChatFile.objects.get(chatfile=chat)
        assert pf.orders.count() == 1 and pf.total_orders == 1

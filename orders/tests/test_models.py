from decimal import Decimal as D
from unittest.mock import patch

import pandas as pd
from django.test import TestCase
from django.utils import timezone

from orders.models import Order, ValidatedFile
from orders.tests.helpers import add_line, make_products, make_user


class OrderIdTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.prefix = timezone.now().strftime("%Y%m%d")

    def new_order(self):
        return Order.objects.create(user=self.user, number="919800000001", order_items="", amount="")

    def test_order_ids_are_sequential_today(self):
        assert [self.new_order().order_id[-5:] for _ in range(2)] == ["00001", "00002"]

    def test_order_id_survives_deletion(self):
        first = self.new_order()
        self.new_order()
        first.delete()
        assert self.new_order().order_id == f"{self.prefix}00003"

    def test_save_retries_on_collision(self):
        taken = self.new_order().order_id
        fresh = f"{self.prefix}00077"
        with patch.object(Order, "generate_order_id", side_effect=[taken, fresh]):
            assert self.new_order().order_id == fresh


class OrderTotalsTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.mango, self.lychee = make_products()
        self.order = Order.objects.create(user=self.user, number="919800000001", order_items="", amount="")

    def test_refresh_totals_and_legacy_strings(self):
        add_line(self.order, self.mango, D("0.5"), "kg")
        add_line(self.order, self.lychee, D("2"), "box")
        self.order.refresh_totals()
        self.order.refresh_from_db()
        assert self.order.total_paise == 56000
        assert self.order.amount == "60+500=560"
        assert self.order.order_items == "Kesar Mango: 0.5 kg, Lychee: 2 box"

    def test_blocking_issues(self):
        self.order.number = "Ravi"
        self.order.refresh_totals()
        assert self.order.blocking_issues() == ["no_phone", "no_lines", "zero_total"]

    def test_unpriced_line_blocks(self):
        add_line(self.order, self.mango, D("1"), "kg")
        add_line(self.order, None, D("1"), "kg", name="Jackfruit")
        self.order.refresh_totals()
        assert self.order.blocking_issues() == ["unpriced_line"]

    def test_reprice_keeps_extractor_flags(self):
        line = add_line(self.order, None, D("1"), "kg", name="Kesar", flags=["ambiguous_product"])
        assert line.flags == ["ambiguous_product", "unknown_product"]
        line.product = self.mango
        line.reprice()
        assert line.flags == ["ambiguous_product"]


class LegacyExtractionTests(TestCase):
    def test_legacy_extraction_is_auto_approved(self):
        from orders.utils import extract_orders_from_validated_file_sync
        user = make_user()
        vf = ValidatedFile.objects.create(user=user, file_name="v.csv", filepath="validatedchatfile/v.csv", filetype="csv")
        df = pd.DataFrame([{"Phone/Name": "919800000001", "Items": "Apples:2", "Total_Amount": "100=100"}])
        with patch("orders.utils.pd.read_csv", return_value=df), \
             patch("orders.utils.calculate_amount_from_items", return_value="100=100"):
            orders = extract_orders_from_validated_file_sync(vf)
        assert len(orders) == 1
        assert orders[0].review_status == "approved" and orders[0].user == user

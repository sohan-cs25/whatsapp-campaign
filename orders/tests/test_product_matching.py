"""Products added or changed after a chat was processed reach the draft orders:
unknown lines are matched by name and draft lines are re-priced."""

from decimal import Decimal as D
from io import StringIO
from unittest.mock import patch

import pandas as pd
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APITestCase

from orders.models import Order, OrderLine, Product
from orders.order_builder import build_orders
from orders.pricing import price_line
from orders.product_matching import match_product
from orders.tests.helpers import make_parsed_file, make_user
from orders.tests.test_builder import row


def week_products():
    return {
        "blueberry": Product.objects.create(key="blueberry", name="Blueberry", price=D("250"), price_unit="g",
                                            pack_size=D("125"), whole_packs_only=True),
        "guava": Product.objects.create(key="thai_guava", name="Thai guavas", price=D("130"), price_unit="kg"),
        "toor": Product.objects.create(key="hand_pounded_toor_dal", name="Hand pounded toor dal", price=D("260"),
                                       price_unit="kg"),
        "moong": Product.objects.create(key="hand_pounded_moong_dal", name="Hand pounded moong dal",
                                        price=D("210"), price_unit="kg"),
    }


class MatchProductTests(TestCase):
    def setUp(self):
        self.p = week_products()
        Product.objects.create(key="old_dal", name="Masoor dal", price=D("1"), price_unit="kg", is_active=False)

    def test_matches_by_words(self):
        assert match_product("Guava") == self.p["guava"]
        assert match_product("Thai Guavas") == self.p["guava"]
        assert match_product("Toor Dal") == self.p["toor"]
        assert match_product("moong dal") == self.p["moong"]
        assert match_product("Blueberries") == self.p["blueberry"]
        assert match_product("blue berry") == self.p["blueberry"]
        assert match_product("hand_pounded_toor_dal") == self.p["toor"]

    def test_no_or_ambiguous_match(self):
        assert match_product("Dal") is None  # toor or moong?
        assert match_product("Wood Pressed Oils") is None
        assert match_product("Masoor dal") is None  # inactive
        assert match_product("") is None and match_product(None) is None


class PackCountUnitTests(TestCase):
    def test_boxes_of_a_pack_priced_product_count_as_packs(self):
        berry = week_products()["blueberry"]
        assert price_line(berry, D("2"), "box").line_total_paise == 50000
        assert price_line(berry, D("1"), "packet").line_total_paise == 25000
        assert price_line(berry, D("125"), "g").line_total_paise == 25000
        assert price_line(berry, D("500"), "g").line_total_paise == 100000

    def test_box_still_mismatches_a_per_kg_product(self):
        guava = week_products()["guava"]
        assert price_line(guava, D("1"), "box").flags == ["unit_mismatch"]


class BuilderMatchesByNameTests(TestCase):
    def test_other_product_linked_by_name(self):
        user = make_user()
        p = week_products()
        (o,) = build_orders(make_parsed_file(user), pd.DataFrame([
            row(product="Guava", product_id=None, base_qty=1000.0, base_unit="g", flags="unknown_product")]))
        (line,) = o.lines.all()
        assert line.product == p["guava"] and line.name == "Thai guavas" and line.line_total_paise == 13000
        assert "unknown_product" not in o.review_flags


class RefreshDraftsTests(APITestCase):
    """The reviewer's scenario: chat processed first, products added afterwards."""

    def setUp(self):
        self.user = make_user()
        self.user.user_permissions.add(*Permission.objects.filter(
            codename__in=["add_product", "change_product", "delete_product"]))
        self.client.force_authenticate(self.user)
        self.pf = make_parsed_file(self.user)
        self.draft = self.order([("Guava", "1000", "g"), ("Blueberry", "2", "box")])
        self.approved = self.order([("Guava", "1000", "g")], review_status="approved")

    def order(self, lines, review_status="draft", status="pending"):
        o = Order.objects.create(user=self.user, parsed_file=self.pf, customer_name="Asha", number="919800000001",
                                 address="C-1", order_items="", amount="", review_status=review_status,
                                 status=status, review_flags=["unknown_product"], needs_review=True)
        for name, qty, unit in lines:
            line = OrderLine(order=o, product=None, name=name, quantity=D(qty), unit=unit)
            line.reprice()
            line.save()
        o.refresh_totals()
        return o

    def add_products(self):
        for b in [{"key": "thai_guava", "name": "Thai guavas", "price": "130", "price_unit": "kg"},
                  {"key": "blueberry", "name": "Blueberry", "price": "250", "price_unit": "g", "pack_size": "125",
                   "whole_packs_only": True}]:
            assert self.client.post("/api/orders/products/", b, format="json").status_code == 201

    def test_adding_products_prices_waiting_draft_orders(self):
        self.add_products()
        self.draft.refresh_from_db()
        assert self.draft.total_paise == 13000 + 50000
        assert [l.product.key for l in self.draft.lines.all()] == ["thai_guava", "blueberry"]
        assert "unknown_product" not in self.draft.review_flags
        assert self.draft.blocking_issues() == [] and self.draft.needs_review is False

    def test_approved_and_sent_orders_untouched(self):
        sent = self.order([("Guava", "1000", "g")], review_status="approved", status="sent")
        self.add_products()
        for o in (self.approved, sent):
            o.refresh_from_db()
            assert o.total_paise == 0 and o.lines.get().product is None

    def test_price_change_reprices_drafts_only(self):
        self.add_products()
        guava = Product.objects.get(key="thai_guava")
        Order.objects.filter(id=self.approved.id).update(review_status="draft")
        self.client.post(f"/api/orders/review/{self.pf.id}/refresh/", format="json")  # price the other one
        Order.objects.filter(id=self.approved.id).update(review_status="approved")
        assert self.client.patch(f"/api/orders/products/{guava.id}/", {"price": "140"},
                                 format="json").status_code == 200
        self.draft.refresh_from_db(); self.approved.refresh_from_db()
        assert self.draft.lines.get(product=guava).line_total_paise == 14000
        assert self.approved.lines.get().line_total_paise == 13000

    def test_refresh_endpoint(self):
        week_products()  # added outside the API (admin, sheet import)
        r = self.client.post(f"/api/orders/review/{self.pf.id}/refresh/", format="json")
        assert r.status_code == 200 and r.data["lines_matched"] == 2 and r.data["orders_updated"] == 1
        self.draft.refresh_from_db()
        assert self.draft.total_paise == 63000

    def test_refresh_other_users_file_404(self):
        self.client.force_authenticate(make_user("other"))
        assert self.client.post(f"/api/orders/review/{self.pf.id}/refresh/", format="json").status_code == 404

    def test_sheet_import_refreshes_drafts(self):
        rows = [{"name": "Thai guavas", "price": 130, "unit": "kg"}]
        with patch("orders.utils.fetch_price_sheet_rows", return_value=rows):
            call_command("import_products_from_sheet", stdout=StringIO())
        self.draft.refresh_from_db()
        assert self.draft.total_paise == 13000

"""Prices for a quantity other than one unit: '₹45 per 250 g', '₹60 per 6 pieces'."""

from decimal import Decimal as D
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APITestCase

from orders.models import Order, OrderLine, Product
from orders.pricing import PricedLine, price_line
from orders.tests.helpers import make_parsed_file, make_user


def product(key, price, unit, pack=1, whole=False):
    return Product.objects.create(key=key, name=key.replace("_", " ").title(), price=D(price), price_unit=unit,
                                  pack_size=D(pack), whole_packs_only=whole)


class PackPricingTests(TestCase):
    def setUp(self):
        self.mushroom = product("mushroom", "45", "g", 250)
        self.banana = product("banana", "60", "piece", 6)
        self.tomato = product("tomato", "20", "kg")
        self.berry = product("blueberry", "199", "g", 125, whole=True)

    def test_whole_packs(self):
        assert price_line(self.mushroom, D("500"), "g") == PricedLine(4500, 9000, [])
        assert price_line(self.mushroom, D("1"), "kg") == PricedLine(4500, 18000, [])
        assert price_line(self.banana, D("12"), "piece") == PricedLine(6000, 12000, [])

    def test_partial_pack_is_proportional_and_flagged(self):
        assert price_line(self.mushroom, D("300"), "g") == PricedLine(4500, 5400, ["partial_pack"])

    def test_per_one_unit_unchanged_and_never_partial(self):
        assert price_line(self.tomato, D("1.5"), "kg") == PricedLine(2000, 3000, [])
        assert price_line(self.tomato, D("500"), "g") == PricedLine(2000, 1000, [])

    def test_whole_packs_only_rounds_up_and_flags(self):
        assert price_line(self.berry, D("200"), "g") == PricedLine(19900, 39800, ["rounded_to_whole_packs"])
        assert price_line(self.berry, D("250"), "g") == PricedLine(19900, 39800, [])

    def test_unit_mismatch_still_detected(self):
        assert price_line(self.banana, D("1"), "kg").flags == ["unit_mismatch"]

    def test_reprice_replaces_old_pack_flags(self):
        user = make_user()
        o = Order.objects.create(user=user, parsed_file=make_parsed_file(user), number="919800000001",
                                 order_items="", amount="")
        line = OrderLine(order=o, product=self.mushroom, name="Mushroom", quantity=D("300"), unit="g",
                         flags=["seller_declined"])
        line.reprice()
        assert line.flags == ["seller_declined", "partial_pack"]
        line.quantity = D("500")
        line.reprice()
        assert line.flags == ["seller_declined"] and line.line_total_paise == 9000


class PackWhatsAppItemTests(TestCase):
    def item(self, prod, qty, unit):
        from orders.whatsapp_service import OrderWhatsAppService
        user = make_user()
        o = Order.objects.create(user=user, parsed_file=make_parsed_file(user), number="919800000001",
                                 order_items="", amount="")
        line = OrderLine(order=o, product=prod, name=prod.name, quantity=D(qty), unit=unit)
        line.reprice()
        line.save()
        it = OrderWhatsAppService.line_to_whatsapp_item(line)
        assert it["quantity"] * it["amount"]["value"] == line.line_total_paise
        return it

    def test_whole_packs_named_with_pack_size(self):
        it = self.item(product("mushroom", "45", "g", 250), "1", "kg")
        assert (it["name"], it["quantity"], it["amount"]["value"]) == ("Mushroom (250 g)", 4, 4500)

    def test_partial_pack_is_one_item(self):
        it = self.item(product("mushroom", "45", "g", 250), "300", "g")
        assert (it["name"], it["quantity"], it["amount"]["value"]) == ("Mushroom (300 g)", 1, 5400)

    def test_rounded_up_packs_sent_as_packs(self):
        it = self.item(product("blueberry", "199", "g", 125, whole=True), "200", "g")
        assert (it["name"], it["quantity"], it["amount"]["value"]) == ("Blueberry (125 g)", 2, 19900)

    def test_per_one_unit_name_unchanged(self):
        it = self.item(product("lychee", "250", "box"), "2", "box")
        assert (it["name"], it["quantity"]) == ("Lychee", 2)


class PackApiAndCatalogTests(APITestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission
        user = make_user()
        user.user_permissions.add(*Permission.objects.filter(codename__in=["add_product", "change_product"]))
        self.client.force_authenticate(user)

    def test_create_with_pack_size(self):
        r = self.client.post("/api/orders/products/", {"key": "mushroom", "name": "Mushroom", "price": "45",
                                                       "price_unit": "g", "pack_size": "250",
                                                       "whole_packs_only": True}, format="json")
        assert r.status_code == 201, r.data
        p = Product.objects.get(key="mushroom")
        assert p.pack_size == D("250") and p.whole_packs_only

    def test_default_pack_size_is_one(self):
        r = self.client.post("/api/orders/products/", {"key": "tomato", "name": "Tomato", "price": "20",
                                                       "price_unit": "kg"}, format="json")
        assert r.status_code == 201 and D(r.data["pack_size"]) == 1 and r.data["whole_packs_only"] is False

    def test_pack_size_must_be_positive(self):
        for bad in ("0", "-5"):
            r = self.client.post("/api/orders/products/", {"key": "x", "name": "X", "price": "1",
                                                           "price_unit": "g", "pack_size": bad}, format="json")
            assert r.status_code == 400 and "pack_size" in r.data

    def test_catalog_shows_pack(self):
        product("mushroom", "45", "g", 250)
        product("tomato", "20", "kg")
        product("blueberry", "199", "g", 125, whole=True)
        cat = {c["id"]: c for c in Product.as_catalog()}
        assert cat["mushroom"]["price_per"] == "250 g" and cat["tomato"]["price_per"] == "kg"
        assert "whole packs" in (cat["blueberry"]["notes"] or "")


class SheetImportPackTests(TestCase):
    def run_import(self, rows):
        out = StringIO()
        with patch("orders.utils.fetch_price_sheet_rows", return_value=rows):
            call_command("import_products_from_sheet", stdout=out)
        return out.getvalue()

    def test_unit_with_quantity(self):
        self.run_import([{"name": "Mushroom", "price": 45, "unit": "250 g"},
                         {"name": "Banana", "price": 60, "unit": "6 pcs"},
                         {"name": "Tomato", "price": 20, "unit": "kg"},
                         {"name": "Spinach", "price": 35, "unit": "Bunch"}])
        got = {p.key: (p.pack_size, p.price_unit) for p in Product.objects.all()}
        assert got == {"mushroom": (D("250"), "g"), "banana": (D("6"), "piece"), "tomato": (D("1"), "kg"),
                       "spinach": (D("1"), "bunch")}


class ProductRowPackTests(SimpleTestCase):
    def test_pack_fields_compared(self):
        from orders_streamlit.product_rows import product_row_changed
        old = {"price": "45.00", "pack_size": "250.000", "whole_packs_only": False}
        assert not product_row_changed(old, {"price": "45.0", "pack_size": "250.0", "whole_packs_only": False})
        assert product_row_changed(old, {"price": "45.0", "pack_size": "500", "whole_packs_only": False})
        assert product_row_changed(old, {"price": "45.0", "pack_size": "250", "whole_packs_only": True})

    def test_price_label(self):
        from orders_streamlit.product_rows import price_label
        assert price_label({"price": "45.00", "pack_size": "250.000", "price_unit": "g"}) == "₹45 per 250 g"
        assert price_label({"price": "20.00", "pack_size": "1.000", "price_unit": "kg"}) == "₹20 per kg"
        assert price_label({"price": "12.50", "pack_size": "6", "price_unit": "piece"}) == "₹12.50 per 6 piece"

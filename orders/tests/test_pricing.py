from decimal import Decimal as D

from django.test import TestCase

from orders.models import Product
from orders.pricing import PricedLine, price_line


def make_product(key="p", name="P", price=D("100"), price_unit="kg", is_active=True):
    return Product.objects.create(key=key, name=name, price=price, price_unit=price_unit, is_active=is_active)


class PriceLineTests(TestCase):
    def setUp(self):
        self.mango = make_product("kesar_mango", "Kesar Mango", D("120"), "kg")
        self.lychee = make_product("lychee", "Lychee", D("250"), "box")
        self.ghee = make_product("ghee", "Ghee", D("900"), "l")

    def test_half_kg_priced_per_kg(self):
        assert price_line(self.mango, D("0.5"), "kg") == PricedLine(12000, 6000, [])

    def test_grams_convert_to_kg(self):
        assert price_line(self.mango, D("500"), "g").line_total_paise == 6000

    def test_ml_convert_to_litre(self):
        assert price_line(self.ghee, D("250"), "ml").line_total_paise == 22500

    def test_boxes(self):
        assert price_line(self.lychee, D("2"), "box") == PricedLine(25000, 50000, [])

    def test_rounds_half_up_to_paise(self):
        p = make_product("half", "Half", D("125"), "kg")
        assert price_line(p, D("0.001"), "kg").line_total_paise == 13  # 12.5 -> 13, not banker's 12

    def test_unit_mismatch_is_flagged(self):
        assert price_line(self.lychee, D("1"), "kg") == PricedLine(25000, 0, ["unit_mismatch"])

    def test_unknown_product(self):
        assert price_line(None, D("1"), "kg") == PricedLine(0, 0, ["unknown_product"])

    def test_missing_quantity(self):
        assert price_line(self.mango, None, "kg").flags == ["missing_quantity"]

    def test_missing_unit_assumes_price_unit(self):
        assert price_line(self.lychee, D("3"), None).line_total_paise == 75000

    def test_as_catalog_skips_inactive(self):
        make_product("old", "Old", D("1"), "kg", is_active=False)
        keys = [p["id"] for p in Product.as_catalog()]
        assert "old" not in keys and "kesar_mango" in keys
        entry = next(p for p in Product.as_catalog() if p["id"] == "kesar_mango")
        assert entry == {"id": "kesar_mango", "name": "Kesar Mango", "price": 120.0,
                         "price_per": "kg", "first_announced_id": "", "notes": None}

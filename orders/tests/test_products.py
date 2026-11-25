from decimal import Decimal as D
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APITestCase

from orders.models import Product
from orders.tests.helpers import make_products, make_user


class ProductApiTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(make_user())
        self.mango, _ = make_products()

    def test_product_delete_deactivates(self):
        assert self.client.delete(f"/api/orders/products/{self.mango.id}/").status_code == 204
        self.mango.refresh_from_db()
        assert self.mango.is_active is False

    def test_create_product(self):
        r = self.client.post("/api/orders/products/", {"key": "atta", "name": "Atta", "price": "60",
                                                       "price_unit": "kg"}, format="json")
        assert r.status_code == 201 and Product.objects.get(key="atta").price == D("60")


def run_import(rows, *args):
    out = StringIO()
    with patch("orders.utils.fetch_price_sheet_rows", return_value=rows):
        call_command("import_products_from_sheet", *args, stdout=out)
    return out.getvalue()


class ImportCommandTests(TestCase):
    def test_import_creates_and_updates(self):
        assert "created 1, updated 0, skipped 0" in run_import([{"name": "Kesar Mango", "price": 120, "unit": "kg"}])
        assert "created 0, updated 1, skipped 0" in run_import([{"name": "Kesar Mango", "price": 130, "unit": "kg"}])
        p = Product.objects.get()
        assert p.key == "kesar_mango" and p.price == D("130")

    def test_import_default_unit(self):
        run_import([{"name": "Lychee", "price": 250, "unit": None}], "--default-unit", "box")
        assert Product.objects.get(key="lychee").price_unit == "box"

    def test_import_rejects_bad_unit(self):
        out = run_import([{"name": "Mango", "price": 120, "unit": "kgs"}])
        assert "skipped 1" in out and not Product.objects.exists()

    def test_dry_run_writes_nothing(self):
        out = run_import([{"name": "Mango", "price": 120, "unit": "kg"}], "--dry-run")
        assert "created 1" in out and not Product.objects.exists()

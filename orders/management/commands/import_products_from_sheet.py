"""Import products and prices from the price Google Sheet (PRICE_LIST_SHEET_URL) into the Product table."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from orders import utils
from orders.models import Product, UNITS


class Command(BaseCommand):
    help = "Create or update Products from the price sheet (columns: item/product/name, price/rate/amount, optional unit)."

    def add_arguments(self, parser):
        parser.add_argument("--default-unit", default="kg", choices=UNITS,
                            help="Unit to use for rows without a unit (default: kg)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving")

    def handle(self, *args, default_unit, dry_run, **options):
        created = updated = skipped = 0
        with transaction.atomic():
            for row in utils.fetch_price_sheet_rows():
                unit = row.get("unit") or default_unit
                key = slugify(row["name"]).replace("-", "_")
                if unit not in UNITS or not key:
                    skipped += 1
                    self.stdout.write(f"skipped '{row['name']}': unit '{unit}' not one of {UNITS}")
                    continue
                values = {"name": row["name"], "price": Decimal(str(row["price"])), "price_unit": unit,
                          "is_active": True}
                _, was_created = Product.objects.update_or_create(key=key, defaults=values)
                created += was_created
                updated += not was_created
            if dry_run:
                transaction.set_rollback(True)
        prefix = "[dry run] " if dry_run else ""
        self.stdout.write(f"{prefix}created {created}, updated {updated}, skipped {skipped}")

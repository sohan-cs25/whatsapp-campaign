"""Import products and prices from the price Google Sheet (PRICE_LIST_SHEET_URL) into the Product table."""

import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from orders import utils
from orders.models import Product, UNITS


UNIT_ALIASES = {"kgs": "kg", "kilo": "kg", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "grm": "g",
                "ltr": "l", "litre": "l", "liter": "l", "pc": "piece", "pcs": "piece", "pieces": "piece",
                "no": "piece", "nos": "piece", "pkt": "packet", "packets": "packet", "boxes": "box",
                "bunches": "bunch", "dozens": "dozen"}


def parse_unit(text):
    """'250 g' -> (250, 'g'), '6 pcs' -> (6, 'piece'), 'kg' -> (1, 'kg'); (None, None) if unreadable."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)?\s*([a-zA-Z]+)\.?\s*", str(text or ""))
    if not m:
        return None, None
    unit = m.group(2).lower()
    unit = UNIT_ALIASES.get(unit, unit)
    try:
        size = Decimal(m.group(1)) if m.group(1) else Decimal(1)
    except InvalidOperation:
        return None, None
    return (size, unit) if unit in UNITS and size > 0 else (None, None)


class Command(BaseCommand):
    help = ("Create or update Products from the price sheet (columns: item/product/name, price/rate/amount, "
            "optional unit such as kg, 250 g or 6 pcs).")

    def add_arguments(self, parser):
        parser.add_argument("--default-unit", default="kg", choices=UNITS,
                            help="Unit to use for rows without a unit (default: kg)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would change without saving")

    def handle(self, *args, default_unit, dry_run, **options):
        created = updated = skipped = 0
        with transaction.atomic():
            for row in utils.fetch_price_sheet_rows():
                raw_unit = row.get("unit") or default_unit
                pack_size, unit = parse_unit(raw_unit)
                key = slugify(row["name"]).replace("-", "_")
                if unit is None or not key:
                    skipped += 1
                    self.stdout.write(f"skipped '{row['name']}': unit '{raw_unit}' is not a quantity of one of {UNITS}")
                    continue
                values = {"name": row["name"], "price": Decimal(str(row["price"])), "price_unit": unit,
                          "pack_size": pack_size, "is_active": True}
                _, was_created = Product.objects.update_or_create(key=key, defaults=values)
                created += was_created
                updated += not was_created
            if dry_run:
                transaction.set_rollback(True)
        prefix = "[dry run] " if dry_run else ""
        self.stdout.write(f"{prefix}created {created}, updated {updated}, skipped {skipped}")

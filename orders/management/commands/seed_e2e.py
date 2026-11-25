"""
Seed the local end-to-end database: a login, the products in e2e/sample_chat.txt and,
with --with-orders, a processed chat file whose orders are ready to review (no LLM call).

Runs only when settings.E2E_MODE is true (whatsapp_campaign.settings_e2e), so it can
never touch the production database.
"""

from decimal import Decimal

import pandas as pd
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from orders.models import ChatFile, Order, ParsedChatFile, Product
from orders.order_builder import build_orders

USERNAME, PASSWORD = "e2e", "e2e-pass-123"
SEED_CHAT_NAME = "e2e_seeded_chat.txt"

PRODUCTS = [
    ("kesar_mango", "Kesar Mango", "120", "kg"),
    ("alphonso_mango", "Alphonso Mango", "900", "dozen"),
    ("lychee", "Lychee", "250", "box"),
    ("tender_coconut", "Tender Coconut", "45", "piece"),
]


def _row(sender, product_id, product, base_qty, base_unit, mid, kind="new", flags="", address="",
         phone=None, needs_review=False):
    return {"date": "01/06/2026", "time": "8:15 AM", "sender": sender, "address": address, "phone": phone,
            "product": product, "product_id": product_id, "in_catalog": product_id is not None,
            "as_written": product, "quantity": None, "unit": None, "base_qty": base_qty,
            "base_unit": base_unit, "kind": kind, "message_ids": mid, "flags": flags,
            "needs_review": needs_review}


# What the extractor would produce for e2e/sample_chat.txt, one case per review situation.
SEED_ROWS = [
    # clean order with a later addition (2 kg + 1 kg)
    _row("919000000001", "kesar_mango", "Kesar Mango", 2000.0, "g", "m7", address="C-710"),
    _row("919000000001", "kesar_mango", "Kesar Mango", 1000.0, "g", "m15", kind="addition", address="C-710"),
    # clean two-product order
    _row("919000000002", "alphonso_mango", "Alphonso Mango", 1.0, "dozen", "m8", address="B-204"),
    _row("919000000002", "lychee", "Lychee", 2.0, "box", "m8", address="B-204"),
    # named sender whose phone number is in a message
    _row("Priya Sharma", "kesar_mango", "Kesar Mango", 500.0, "g", "m9", address="A-101", phone="90000 00003"),
    _row("Priya Sharma", "lychee", "Lychee", 1.0, "box", "m9", address="A-101", phone="90000 00003"),
    # cancellation followed by a replacement
    _row("919000000005", "kesar_mango", "Kesar Mango", 1000.0, "g", "m13", address="E-302"),
    _row("919000000005", "kesar_mango", "Kesar Mango", -1000.0, "g", "m14", kind="cancellation", address="E-302"),
    _row("919000000005", "lychee", "Lychee", 2.0, "box", "m14", address="E-302"),
    # no phone number and a product that is not in the catalog
    _row("Ramesh", None, "Dragon Fruit", 2.0, "piece", "m18", flags="unknown_product", address="F-11",
         needs_review=True),
    _row("Ramesh", "kesar_mango", "Kesar Mango", 1000.0, "g", "m18", address="F-11"),
]


class Command(BaseCommand):
    help = "Seed the local end-to-end test database (only with settings_e2e)."

    def add_arguments(self, parser):
        parser.add_argument("--with-orders", action="store_true",
                            help="Also create a processed chat file with orders ready to review.")

    def handle(self, *args, **opts):
        if not getattr(settings, "E2E_MODE", False):
            raise CommandError("seed_e2e only runs with E2E settings "
                               "(--settings=whatsapp_campaign.settings_e2e); refusing to touch this database.")
        with transaction.atomic():
            user = self._user()
            for key, name, price, unit in PRODUCTS:
                Product.objects.update_or_create(key=key, defaults={
                    "name": name, "price": Decimal(price), "price_unit": unit, "is_active": True})
            self.stdout.write(f"User '{USERNAME}' / '{PASSWORD}', {len(PRODUCTS)} products")
            if opts["with_orders"]:
                orders = self._orders(user)
                self.stdout.write(f"Seeded processed file with {len(orders)} orders to review")

    def _user(self):
        user, created = User.objects.get_or_create(username=USERNAME, defaults={"email": "e2e@example.com"})
        if created or not user.check_password(PASSWORD):
            user.set_password(PASSWORD)
            user.save()
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="orders", codename__in=["add_product", "change_product", "delete_product"]))
        return user

    def _orders(self, user):
        for old in ChatFile.objects.filter(user=user, filename=SEED_CHAT_NAME):
            Order.objects.filter(parsed_file__chatfile=old).delete()
            old.delete()
        chat = ChatFile.objects.create(user=user, filename=SEED_CHAT_NAME, filepath=f"chatfile/{SEED_CHAT_NAME}",
                                       filetype="text", is_processed=True)
        pf = ParsedChatFile.objects.create(user=user, chatfile=chat, file_name="e2e_seeded_chat_processed.xlsx",
                                           processed_file_path="processedchatfile/e2e_seeded_chat_processed.xlsx",
                                           total_messages=25)
        orders = build_orders(pf, pd.DataFrame(SEED_ROWS))
        pf.total_orders = len(orders)
        pf.save(update_fields=["total_orders"])
        return orders

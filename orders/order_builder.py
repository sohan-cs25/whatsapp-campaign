"""
Turn the extractor's order table (order_extractor.postprocess output) into one priced
Order per customer per processed chat file, with one OrderLine per product.
"""

import re
from collections import Counter, OrderedDict
from decimal import Decimal
from typing import List

import pandas as pd
from django.db import transaction

from .models import INFO_FLAGS, PRICING_FLAGS, CustomerContact, Order, OrderLine, Product
from .product_matching import match_product


class RebuildBlocked(Exception):
    """Orders for this file have already been approved or sent; they cannot be rebuilt."""


def _present(v) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v))


def _split_flags(v) -> List[str]:
    return [f for f in str(v).split(",") if f] if _present(v) else []


def _phone_for(sender: str, phones: List) -> str:
    if re.fullmatch(r"\d{10,15}", sender or ""):
        return sender
    for p in phones:
        if _present(p):
            digits = re.sub(r"\D", "", str(p))
            if len(digits) == 10:
                digits = "91" + digits
            if 10 <= len(digits) <= 15:
                return digits
    return ""


def _decimal(x) -> Decimal:
    return Decimal(str(round(float(x), 3)))


@transaction.atomic
def build_orders(parsed_file, orders_df: pd.DataFrame) -> List[Order]:
    existing = list(parsed_file.orders.all())
    if any(o.review_status != "draft" or o.status != "pending" for o in existing):
        raise RebuildBlocked(f"Orders for {parsed_file.file_name} were already approved or sent")
    for o in existing:
        o.delete()
    if orders_df is None or orders_df.empty:
        return []

    products = {p.key: p for p in Product.objects.all()}
    active_products = [p for p in products.values() if p.is_active]
    built = []
    for sender, rows in orders_df.groupby("sender", sort=False):
        records = rows.to_dict("records")
        order_flags = set()

        # Group item rows into lines; rows with no quantity each become their own line.
        groups = OrderedDict()
        for i, r in enumerate(records):
            if not _present(r.get("product")):
                if r.get("kind") == "cancellation":
                    order_flags.add("cancellation_without_items")
                continue
            ident = r.get("product_id") if _present(r.get("product_id")) else r["product"]
            key = (ident, r.get("base_unit")) if _present(r.get("base_qty")) else ("__noqty__", i)
            groups.setdefault(key, []).append(r)

        line_specs = []
        for (ident, _), grp in groups.items():
            first = grp[0]
            qtys = [r["base_qty"] for r in grp if _present(r.get("base_qty"))]
            total = sum(qtys) if qtys else None
            if total is not None and total <= 0:
                order_flags.add("had_cancellation")
                continue
            if any(r.get("kind") == "cancellation" for r in grp):
                order_flags.add("had_cancellation")
            pid = first.get("product_id") if _present(first.get("product_id")) else None
            product = products.get(pid) if pid else None
            if product is None:  # not in the catalog the AI saw: try the item's name
                product = match_product(first["product"], active_products)
            line_specs.append({
                "product": product,
                "name": product.name if product else str(first["product"]),
                "quantity": _decimal(total) if total is not None else None,
                "unit": first.get("base_unit") if _present(first.get("base_unit")) else "",
                "as_written": "; ".join(str(r["as_written"]) for r in grp if _present(r.get("as_written"))),
                "message_ids": ",".join(OrderedDict.fromkeys(
                    m for r in grp for m in str(r["message_ids"]).split(",") if m)),
                "flags": sorted({f for r in grp for f in _split_flags(r.get("flags"))}),
            })

        if not line_specs and "cancellation_without_items" not in order_flags:
            continue  # everything this customer ordered was cancelled

        addresses = Counter(r["address"] for r in records if _present(r.get("address")) and r["address"])
        address = addresses.most_common(1)[0][0] if addresses else ""
        number = _phone_for(str(sender), [r.get("phone") for r in records])
        if not number:  # chat shows a saved contact name only: look the flat up
            number = CustomerContact.phone_for(parsed_file.user, address)
            if number:
                order_flags.add("phone_from_directory")
        order = Order.objects.create(
            user=parsed_file.user,
            parsed_file=parsed_file,
            customer_name=str(sender)[:120],
            chat_sender=str(sender)[:120],
            number=number,
            address=address,
            order_items="",
            amount="",
            review_status="draft",
        )
        for spec in line_specs:
            line = OrderLine(order=order, **spec)
            line.reprice()
            line.save()
        order.refresh_totals()

        # pricing flags come from the lines as priced here, not from the extractor's rows
        row_flags = {f for r in records for f in _split_flags(r.get("flags"))} - PRICING_FLAGS
        line_flags = {f for l in order.lines.all() for f in l.flags}
        order.review_flags = sorted(row_flags | line_flags | order_flags)
        order.needs_review = (any(bool(r.get("needs_review")) for r in records)
                              or bool(set(order.review_flags) - INFO_FLAGS)
                              or bool(order.blocking_issues()))
        order.save(update_fields=["review_flags", "needs_review", "updated_at"])
        built.append(order)
    return built

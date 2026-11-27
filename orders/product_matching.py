"""
Match an order line's item name to a Product, and bring draft orders up to date with the
product table (lines matched by name, every line re-priced at the current price).

Used when orders are built (the AI may only name an item, e.g. 'Guava', when the product is
'Thai guavas'), and again whenever products change after a chat was processed.
"""

import re

from .models import Order, Product


def _words(text):
    words = []
    for w in re.findall(r"[a-z]+", str(text or "").lower().replace("_", " ")):
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"                                   # berries -> berry
        elif len(w) > 3 and w.endswith("oes"):
            w = w[:-2]                                         # tomatoes -> tomato
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]                                         # guavas -> guava
        words.append(w)
    return words


def match_product(name, products=None):
    """The one active product this name refers to, or None if none or several match.
    Tries, in order: same words ignoring spaces ('blue berry' = 'Blueberry'); all the
    name's words in the product's name or key ('Toor Dal' in 'Hand pounded toor dal');
    all the product's words in the name."""
    words = _words(name)
    if not words:
        return None
    products = list(products) if products is not None else list(Product.objects.filter(is_active=True))
    wanted, compact = set(words), "".join(words)
    candidates = [(p, set(_words(p.name)), set(_words(p.key)), "".join(_words(p.name))) for p in products
                  if p.is_active]
    tiers = [
        lambda pw, kw, pc: compact == pc or compact == "".join(sorted(kw)) or wanted == kw,
        lambda pw, kw, pc: wanted <= pw or wanted <= kw,
        lambda pw, kw, pc: bool(pw) and pw <= wanted,
    ]
    for test in tiers:
        hits = [p for p, pw, kw, pc in candidates if test(pw, kw, pc)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            return None  # ambiguous: 'Dal' could be toor or moong
    return None


def refresh_draft_orders(orders=None) -> dict:
    """Match unknown lines to products by name and re-price every line of the draft, unsent
    orders given (default: all). Approved and sent orders are never changed."""
    orders = Order.objects.all() if orders is None else orders
    products = list(Product.objects.filter(is_active=True))
    stats = {"lines_matched": 0, "lines_repriced": 0, "orders_updated": 0}
    for order in orders.filter(review_status='draft', status='pending').prefetch_related('lines__product'):
        changed = False
        for line in order.lines.all():
            before = (line.product_id, line.unit_price_paise, line.line_total_paise, list(line.flags or []))
            if line.product is None:
                product = match_product(line.name, products)
                if product is not None:
                    line.product, line.name = product, product.name
                    stats["lines_matched"] += 1
            line.reprice()
            if (line.product_id, line.unit_price_paise, line.line_total_paise, line.flags) != before:
                line.save()
                changed = True
                if before[0] is not None:
                    stats["lines_repriced"] += 1
        if changed:
            order.refresh_totals()
            order.recompute_review_state()
            stats["orders_updated"] += 1
    return stats

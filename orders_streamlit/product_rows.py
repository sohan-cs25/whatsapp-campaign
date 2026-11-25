"""Pure helpers for the products editor (no Streamlit import, so they can be unit tested)."""

from decimal import Decimal, InvalidOperation


def _price(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return v


def product_row_changed(old: dict, body: dict) -> bool:
    """True if an edited product row differs from what the API returned. Prices compare as
    numbers, so the API's "120.00" and the editor's 120.0 count as the same."""
    for k, v in body.items():
        if k == "price":
            if _price(old.get(k)) != _price(v):
                return True
        elif k == "is_active":
            if bool(old.get(k)) != bool(v):
                return True
        elif str(old.get(k)) != str(v):
            return True
    return False

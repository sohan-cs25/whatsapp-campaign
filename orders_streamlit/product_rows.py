"""Pure helpers for the products editor (no Streamlit import, so they can be unit tested)."""

from decimal import Decimal, InvalidOperation


def _price(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return v


NUMERIC = {"price", "pack_size"}
BOOLEAN = {"is_active", "whole_packs_only"}


def product_row_changed(old: dict, body: dict) -> bool:
    """True if an edited product row differs from what the API returned. Numbers compare as
    numbers, so the API's "120.00" and the editor's 120.0 count as the same."""
    for k, v in body.items():
        if k in NUMERIC:
            if _price(old.get(k)) != _price(v):
                return True
        elif k in BOOLEAN:
            if bool(old.get(k)) != bool(v):
                return True
        elif str(old.get(k)) != str(v):
            return True
    return False


def _num(v) -> str:
    d = _price(v)
    if not isinstance(d, Decimal):
        return str(v)
    d = d.normalize()
    return format(d, "f") if d == d.to_integral_value() else format(d.quantize(Decimal("0.01")), "f")


def price_label(p: dict) -> str:
    """'₹45 per 250 g', '₹20 per kg'."""
    pack = _price(p.get("pack_size") or 1)
    per = p.get("price_unit", "") if pack == 1 else f"{_num(pack)} {p.get('price_unit', '')}"
    return f"₹{_num(p.get('price'))} per {per}"

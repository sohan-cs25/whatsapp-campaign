"""Line pricing in integer paise. Pure functions; the only conversions are kg<->g and l<->ml.

A product's price is for pack_size x price_unit (default 1): "45 per 250 g" is price 45,
price_unit g, pack_size 250. An order is priced as packs x price, where packs = quantity
(in price_unit) / pack_size. Part of a pack is priced proportionally and flagged
partial_pack, or rounded up and flagged rounded_to_whole_packs for whole_packs_only products."""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from typing import List, Optional

# unit -> (base unit, multiplier to base)
_BASE = {"kg": ("g", Decimal(1000)), "g": ("g", Decimal(1)),
         "l": ("ml", Decimal(1000)), "ml": ("ml", Decimal(1))}


@dataclass
class PricedLine:
    unit_price_paise: int
    line_total_paise: int
    flags: List[str] = field(default_factory=list)


def to_price_unit(quantity: Decimal, unit: Optional[str], price_unit: str) -> Optional[Decimal]:
    """Express quantity in price_unit. None when the units cannot be converted."""
    unit = unit or price_unit
    if unit == price_unit:
        return Decimal(quantity)
    a, b = _BASE.get(unit), _BASE.get(price_unit)
    if a and b and a[0] == b[0]:
        return Decimal(quantity) * a[1] / b[1]
    return None


def price_line(product, quantity: Optional[Decimal], unit: Optional[str]) -> PricedLine:
    if product is None:
        return PricedLine(0, 0, ["unknown_product"])
    unit_price = int((product.price * 100).quantize(Decimal("1"), ROUND_HALF_UP))
    if quantity is None:
        return PricedLine(unit_price, 0, ["missing_quantity"])
    qty = to_price_unit(Decimal(quantity), unit, product.price_unit)
    if qty is None:
        return PricedLine(unit_price, 0, ["unit_mismatch"])
    pack_size = Decimal(getattr(product, "pack_size", 1) or 1)
    packs = qty / pack_size
    flags = []
    if packs != packs.to_integral_value():
        if getattr(product, "whole_packs_only", False):
            packs = packs.to_integral_value(ROUND_CEILING)
            flags.append("rounded_to_whole_packs")
        elif pack_size != 1:
            flags.append("partial_pack")
    total = int((packs * unit_price).quantize(Decimal("1"), ROUND_HALF_UP))
    return PricedLine(unit_price, total, flags)

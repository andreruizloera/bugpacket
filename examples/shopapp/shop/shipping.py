"""Shipping cost rules: weight tiers plus a free-shipping threshold."""

from __future__ import annotations

FREE_SHIPPING_THRESHOLD_CENTS = 5000

# (max_weight_grams, cost_cents); tiers are checked in order.
WEIGHT_TIERS: list[tuple[int, int]] = [
    (250, 450),
    (1000, 750),
    (5000, 1250),
]

OVERWEIGHT_COST_CENTS = 2500


def shipping_cents(order_total_cents: int, weight_grams: int) -> int:
    """Shipping cost for an order. Free above the threshold."""
    if order_total_cents < 0 or weight_grams < 0:
        raise ValueError("order total and weight must be non-negative")
    if order_total_cents >= FREE_SHIPPING_THRESHOLD_CENTS:
        return 0
    for max_weight, cost in WEIGHT_TIERS:
        if weight_grams <= max_weight:
            return cost
    return OVERWEIGHT_COST_CENTS


def estimate_days(weight_grams: int, expedited: bool = False) -> int:
    """Rough delivery estimate in business days."""
    base = 2 if weight_grams <= 1000 else 4
    return max(1, base - 1) if expedited else base

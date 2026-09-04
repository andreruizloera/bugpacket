"""Order totals: subtotal, coupons, and tax."""

from __future__ import annotations

TAX_RATE = 0.0875  # combined state and local sales tax


def subtotal_cents(items: list[dict]) -> int:
    """Sum of price * quantity across the cart, in cents."""
    return sum(item["price_cents"] * item["qty"] for item in items)


def apply_coupon(amount_cents: int, coupon: dict) -> int:
    """Apply a percent-off coupon to an amount, rounding down."""
    percent = coupon["percent"]
    if not 0 <= percent <= 100:
        raise ValueError(f"coupon percent out of range: {percent}")
    return amount_cents - (amount_cents * percent) // 100


def total_cents(items: list[dict], coupon: dict | None = None) -> int:
    """Final charge for the cart: subtotal, minus coupon, plus tax."""
    amount = subtotal_cents(items)
    if coupon is not None:
        amount = apply_coupon(amount, coupon)
    tax = round(amount * TAX_RATE)
    return amount + tax

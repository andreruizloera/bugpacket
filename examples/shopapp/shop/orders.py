"""Order assembly: cart plus user plus shipping equals an order record."""

from __future__ import annotations

from dataclasses import dataclass

from shop.cart import Cart
from shop.shipping import shipping_cents
from shop.users import User


@dataclass(frozen=True)
class Order:
    user_email: str
    items: list[dict]
    charge_cents: int
    shipping_cents: int

    @property
    def grand_total_cents(self) -> int:
        return self.charge_cents + self.shipping_cents


def place_order(
    user: User,
    cart: Cart,
    weight_grams: int,
    coupon: dict | None = None,
) -> Order:
    """Validate the shipping address, price the cart, and build the order."""
    address = user.default_address()
    problems = address.validate()
    if problems:
        raise ValueError(f"bad shipping address: {'; '.join(problems)}")

    charge = cart.checkout(coupon)
    ship = shipping_cents(charge, weight_grams)
    return Order(
        user_email=user.email,
        items=cart.items,
        charge_cents=charge,
        shipping_cents=ship,
    )

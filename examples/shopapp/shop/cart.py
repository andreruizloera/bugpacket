"""A shopping cart that delegates totals to the payment module."""

from __future__ import annotations

from shop.payment import total_cents


class Cart:
    def __init__(self) -> None:
        self._items: list[dict] = []

    def add(self, name: str, price_cents: int, qty: int = 1) -> None:
        if price_cents < 0:
            raise ValueError("price_cents must be non-negative")
        if qty < 1:
            raise ValueError("qty must be at least 1")
        self._items.append({"name": name, "price_cents": price_cents, "qty": qty})

    @property
    def items(self) -> list[dict]:
        return list(self._items)

    def item_count(self) -> int:
        return sum(item["qty"] for item in self._items)

    def checkout(self, coupon: dict | None = None) -> int:
        """Return the amount to charge, in cents."""
        if not self._items:
            raise ValueError("cannot check out an empty cart")
        return total_cents(self._items, coupon)

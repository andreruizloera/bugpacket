"""In-memory stock tracking with reservations."""

from __future__ import annotations


class OutOfStockError(Exception):
    pass


class Inventory:
    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self._stock: dict[str, int] = dict(initial or {})
        self._reserved: dict[str, int] = {}

    def available(self, sku: str) -> int:
        return self._stock.get(sku, 0) - self._reserved.get(sku, 0)

    def restock(self, sku: str, qty: int) -> None:
        if qty < 0:
            raise ValueError("restock qty must be non-negative")
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def reserve(self, sku: str, qty: int) -> None:
        if qty < 1:
            raise ValueError("reserve qty must be at least 1")
        if self.available(sku) < qty:
            raise OutOfStockError(f"{sku}: requested {qty}, available {self.available(sku)}")
        self._reserved[sku] = self._reserved.get(sku, 0) + qty

    def release(self, sku: str, qty: int) -> None:
        held = self._reserved.get(sku, 0)
        self._reserved[sku] = max(0, held - qty)

    def commit(self, sku: str, qty: int) -> None:
        """Convert a reservation into a real deduction."""
        held = self._reserved.get(sku, 0)
        if held < qty:
            raise ValueError(f"{sku}: committing {qty} but only {held} reserved")
        self._reserved[sku] = held - qty
        self._stock[sku] = self._stock.get(sku, 0) - qty

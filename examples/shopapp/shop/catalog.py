"""Product catalog with lookup and simple search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int
    category: str


PRODUCTS: dict[str, Product] = {
    p.sku: p
    for p in [
        Product("NB-100", "Dotted notebook", 1299, "stationery"),
        Product("NB-200", "Grid notebook", 1399, "stationery"),
        Product("PEN-01", "Gel pen, black", 249, "stationery"),
        Product("PEN-02", "Gel pen, blue", 249, "stationery"),
        Product("MUG-01", "Ceramic mug, 12oz", 1650, "kitchen"),
        Product("MUG-02", "Travel mug, 16oz", 2450, "kitchen"),
        Product("TEE-S", "Logo tee, small", 1800, "apparel"),
        Product("TEE-M", "Logo tee, medium", 1800, "apparel"),
        Product("BAG-01", "Canvas tote", 2200, "apparel"),
        Product("STK-01", "Sticker pack", 599, "stationery"),
    ]
}


def get_product(sku: str) -> Product:
    try:
        return PRODUCTS[sku]
    except KeyError:
        raise LookupError(f"unknown sku: {sku}") from None


def search(term: str) -> list[Product]:
    """Case-insensitive substring search over product names."""
    needle = term.strip().lower()
    if not needle:
        return []
    return sorted(
        (p for p in PRODUCTS.values() if needle in p.name.lower()),
        key=lambda p: p.sku,
    )


def by_category(category: str) -> list[Product]:
    return sorted(
        (p for p in PRODUCTS.values() if p.category == category),
        key=lambda p: p.sku,
    )

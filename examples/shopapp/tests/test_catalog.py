import pytest

from shop.catalog import by_category, get_product, search


def test_lookup_known_sku():
    assert get_product("MUG-01").price_cents == 1650


def test_unknown_sku_raises():
    with pytest.raises(LookupError):
        get_product("NOPE-99")


def test_search_is_case_insensitive():
    names = [p.name for p in search("NOTEBOOK")]
    assert names == ["Dotted notebook", "Grid notebook"]


def test_by_category_sorted_by_sku():
    skus = [p.sku for p in by_category("stationery")]
    assert skus == sorted(skus)

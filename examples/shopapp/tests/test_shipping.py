import pytest

from shop.shipping import estimate_days, shipping_cents


def test_free_shipping_over_threshold():
    assert shipping_cents(5000, 3000) == 0


def test_weight_tiers():
    assert shipping_cents(1000, 200) == 450
    assert shipping_cents(1000, 900) == 750
    assert shipping_cents(1000, 4500) == 1250
    assert shipping_cents(1000, 9000) == 2500


def test_negative_inputs_rejected():
    with pytest.raises(ValueError):
        shipping_cents(-1, 100)


def test_expedited_estimate_is_faster():
    assert estimate_days(500, expedited=True) < estimate_days(500)

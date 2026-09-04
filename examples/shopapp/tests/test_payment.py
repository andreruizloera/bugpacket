from shop.cart import Cart


def make_cart() -> Cart:
    cart = Cart()
    cart.add("Dotted notebook", 1299, qty=2)
    cart.add("Gel pen, black", 249)
    return cart


def test_total_without_coupon():
    # subtotal 2847, tax round(2847 * 0.0875) = 249
    assert make_cart().checkout() == 3096


def test_total_with_percent_coupon():
    coupon = {"code": "SAVE10", "percent": 10}
    # 2847 - 284 = 2563, tax round(2563 * 0.0875) = 224
    assert make_cart().checkout(coupon) == 2787


def test_bigger_coupon_never_increases_total():
    small = make_cart().checkout({"code": "SAVE10", "percent": 10})
    big = make_cart().checkout({"code": "SAVE25", "percent": 25})
    assert big <= small

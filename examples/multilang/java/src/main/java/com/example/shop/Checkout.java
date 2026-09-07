package com.example.shop;

import java.util.List;
import java.util.Map;

public final class Checkout {
    public static int run(List<Item> items, Map<String, Integer> coupon) {
        try {
            return Cart.checkout(items, coupon);
        } catch (RuntimeException e) {
            throw new IllegalStateException("checkout failed for " + items.size() + " item(s)", e);
        }
    }
}

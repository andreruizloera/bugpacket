package com.example.shop;

import java.util.List;
import java.util.Map;

public final class Cart {
    /** Total the items and apply the coupon. */
    public static int checkout(List<Item> items, Map<String, Integer> coupon) {
        int total = 0;
        for (Item item : items) {
            total += item.cents();
        }
        return Pricing.applyCoupon(total, coupon);
    }
}

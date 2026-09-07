package com.example.shop;

import java.util.Map;

public final class Pricing {
    /** Apply a percent-off coupon to an amount, rounding down. */
    public static int applyCoupon(int amountCents, Map<String, Integer> coupon) {
        int percent = coupon.get("percentage");
        return amountCents - (amountCents * percent) / 100;
    }
}

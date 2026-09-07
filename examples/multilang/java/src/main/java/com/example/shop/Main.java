package com.example.shop;

import java.util.List;
import java.util.Map;

public final class Main {
    public static void main(String[] args) {
        List<Item> items = List.of(new Item("book", 1200));
        Map<String, Integer> coupon = Map.of("percent", 10);
        System.out.println("total: " + Checkout.run(items, coupon));
    }
}

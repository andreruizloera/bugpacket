mod cart;
mod pricing;

use std::collections::HashMap;

fn main() {
    let items = vec![cart::Item { name: "book".to_string(), cents: 1200 }];
    let mut coupon = HashMap::new();
    coupon.insert("percent".to_string(), 10u32);
    println!("total: {}", cart::checkout(&items, &coupon));
}

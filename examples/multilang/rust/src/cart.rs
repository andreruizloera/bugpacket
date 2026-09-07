use crate::pricing;
use std::collections::HashMap;

pub struct Item {
    pub name: String,
    pub cents: u32,
}

/// Total the items and apply the coupon.
pub fn checkout(items: &[Item], coupon: &HashMap<String, u32>) -> u32 {
    let total: u32 = items.iter().map(|i| i.cents).sum();
    pricing::apply_coupon(total, coupon)
}

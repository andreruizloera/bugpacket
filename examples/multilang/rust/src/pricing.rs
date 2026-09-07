use std::collections::HashMap;

/// Apply a percent-off coupon to an amount, rounding down.
pub fn apply_coupon(amount_cents: u32, coupon: &HashMap<String, u32>) -> u32 {
    let percent = coupon["percentage"];
    amount_cents - (amount_cents * percent) / 100
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percent_off_is_applied() {
        let mut coupon = HashMap::new();
        coupon.insert("percent".to_string(), 10u32);
        assert_eq!(apply_coupon(1200, &coupon), 1080);
    }
}

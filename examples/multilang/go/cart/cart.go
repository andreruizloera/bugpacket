package cart

import "github.com/example/shop/pricing"

type Item struct {
	Name  string
	Cents int
}

// Checkout totals the items and applies the coupon.
func Checkout(items []Item, coupon map[string]int) int {
	total := 0
	for _, item := range items {
		total += item.Cents
	}
	return pricing.ApplyCoupon(total, coupon)
}

// Receipt renders the nth line of the order receipt.
func Receipt(items []Item, n int) string {
	return items[n].Name
}

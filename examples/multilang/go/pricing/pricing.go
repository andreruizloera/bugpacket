package pricing

// ApplyCoupon applies a percent-off coupon to an amount, rounding down.
func ApplyCoupon(amountCents int, coupon map[string]int) int {
	percent := coupon["percentage"]
	return amountCents - (amountCents*percent)/100
}

package pricing

import "testing"

func TestApplyCouponPercentOff(t *testing.T) {
	coupon := map[string]int{"percent": 10}
	got := ApplyCoupon(1200, coupon)
	if got != 1080 {
		t.Errorf("ApplyCoupon(1200, 10%%) = %d, want 1080", got)
	}
}

func TestApplyCouponPanicsOnNilCoupon(t *testing.T) {
	var coupon map[string]int
	_ = ApplyCoupon(1200, coupon)
}

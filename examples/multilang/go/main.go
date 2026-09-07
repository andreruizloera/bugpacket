package main

import (
	"fmt"

	"github.com/example/shop/cart"
)

func main() {
	items := []cart.Item{{Name: "book", Cents: 1200}}
	coupon := map[string]int{"percent": 10}
	fmt.Println("total:", cart.Checkout(items, coupon))
	fmt.Println("line 2:", cart.Receipt(items, 2))
}

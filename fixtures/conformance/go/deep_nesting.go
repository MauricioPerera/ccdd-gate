package main

func deep_nesting(items []int) int {
	for _, a := range items {
		if a {
			for a {
				select {
				default:
					if a {
						return a
					}
				}
			}
		}
	}
	return 0
}
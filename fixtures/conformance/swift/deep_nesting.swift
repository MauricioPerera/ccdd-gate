func deep_nesting(x: Int) -> Int {
    for _ in 0..<x {
        if x > 0 {
            while x > 0 {
                do {
                    if x > 0 {
                        return x
                    }
                }
            }
        }
    }
    return x
}

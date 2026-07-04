fn deep_nesting(items: &[i32]) -> Option<i32> {
    for a in items {
        if a {
            while a {
                unsafe {
                    if a {
                        return Some(a);
                    }
                }
            }
        }
    }
    None
}
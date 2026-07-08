int deep_nesting(int x) {
    for (int i = 0; i < x; i++) {
        if (x > 0) {
            while (x > 0) {
                cleanup: {
                    if (x > 0) {
                        return x;
                    }
                }
            }
        }
    }
    return x;
}

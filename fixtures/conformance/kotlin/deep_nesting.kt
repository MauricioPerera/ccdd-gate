// Anidamiento profundo (5 niveles: for>if>while>try>if). try/finally anida SIN ser
// decision (analogo del `with` de Python; catch_block seria la decision).
fun deep_nesting(items: IntArray): Int {
    for (a in items) {
        if (a > 0) {
            while (a > 0) {
                try {
                    if (a > 0) {
                        return a
                    }
                } finally {
                }
            }
        }
    }
    return 0
}

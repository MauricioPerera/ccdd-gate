public class deep_nesting {
    public static int deep_nesting(int[] items) {
        for (int a : items) {
            if (a > 0) {
                while (a > 0) {
                    try {
                        if (a > 0) {
                            return a;
                        }
                    } finally {
                    }
                }
            }
        }
        return 0;
    }
}

"""Property-test CONGELADO de clamp. Oráculo independiente (sorted median), no importado del target."""
import random
import unittest

from clamp import clamp

EXAMPLES = [((5, 0, 10), 5), ((-3, 0, 10), 0), ((20, 0, 10), 10)]


class TestClamp(unittest.TestCase):
    def test_examples_fixed(self):
        for args, expected in EXAMPLES:
            self.assertEqual(clamp(*args), expected, msg=str(args))

    def test_properties_random(self):
        rnd = random.Random(20240601)
        for _ in range(500):
            lo = rnd.randint(-1000, 1000)
            hi = lo + rnd.randint(0, 2000)
            x = rnd.randint(-3000, 3000)
            r = clamp(x, lo, hi)
            self.assertEqual(r, sorted([lo, x, hi])[1])   # oráculo independiente
            self.assertTrue(lo <= r <= hi)
            self.assertIn(r, (x, lo, hi))
            self.assertEqual(clamp(r, lo, hi), r)          # idempotencia


if __name__ == "__main__":
    unittest.main()

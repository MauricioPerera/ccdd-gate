"""Property-test CONGELADO de popcount. Oráculo independiente (bin().count), no importado del target."""
import random
import unittest

from popcount import popcount

EXAMPLES = [(0, 0), (7, 3), (255, 8)]


class TestPopcount(unittest.TestCase):
    def test_examples_fixed(self):
        for n, expected in EXAMPLES:
            self.assertEqual(popcount(n), expected, msg=str(n))

    def test_properties_random(self):
        rnd = random.Random(7777)
        for _ in range(500):
            n = rnd.randint(0, 2 ** 64)
            r = popcount(n)
            self.assertEqual(r, bin(n).count("1"))   # oráculo independiente
            self.assertTrue(0 <= r <= n.bit_length())

    def test_powers_of_two(self):
        for k in range(64):
            self.assertEqual(popcount(2 ** k), 1)


if __name__ == "__main__":
    unittest.main()

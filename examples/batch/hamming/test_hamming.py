"""Property-test CONGELADO de hamming_distance. Oráculo independiente (zip+sum), no importado del target."""
import random
import unittest

from hamming import hamming_distance

EXAMPLES = [((b"abc", b"abc"), 0), ((b"abc", b"abd"), 1), ((b"\x00\x00", b"\xff\xff"), 2)]


class TestHamming(unittest.TestCase):
    def test_examples_fixed(self):
        for args, expected in EXAMPLES:
            self.assertEqual(hamming_distance(*args), expected, msg=str(args))

    def test_properties_random(self):
        rnd = random.Random(31337)
        for _ in range(500):
            n = rnd.randint(0, 32)
            a = bytes(rnd.randrange(256) for _ in range(n))
            b = bytes(rnd.randrange(256) for _ in range(n))
            r = hamming_distance(a, b)
            self.assertEqual(r, sum(x != y for x, y in zip(a, b)))   # oráculo independiente
            self.assertTrue(0 <= r <= n)
            self.assertEqual(r, hamming_distance(b, a))              # simetría
            self.assertEqual(hamming_distance(a, a), 0)              # reflexividad

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            hamming_distance(b"abc", b"ab")


if __name__ == "__main__":
    unittest.main()

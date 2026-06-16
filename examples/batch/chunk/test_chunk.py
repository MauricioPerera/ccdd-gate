"""Property-test CONGELADO de chunk. Oráculo independiente (reconstrucción + longitudes), no del target."""
import random
import unittest

from chunk import chunk

EXAMPLES = [(([1, 2, 3, 4], 2), [[1, 2], [3, 4]]),
            (([1, 2, 3], 2), [[1, 2], [3]]),
            (([], 3), [])]


class TestChunk(unittest.TestCase):
    def test_examples_fixed(self):
        for args, expected in EXAMPLES:
            self.assertEqual(chunk(*args), expected, msg=str(args))

    def test_properties_random(self):
        rnd = random.Random(909090)
        for _ in range(500):
            items = [rnd.randint(0, 99) for _ in range(rnd.randint(0, 30))]
            size = rnd.randint(1, 8)
            out = chunk(items, size)
            flat = [x for sub in out for x in sub]
            self.assertEqual(flat, items)                              # reconstrucción exacta
            for sub in out[:-1]:
                self.assertEqual(len(sub), size)                       # llenas salvo la última
            if out:
                self.assertTrue(1 <= len(out[-1]) <= size)

    def test_bad_size_raises(self):
        with self.assertRaises(ValueError):
            chunk([1, 2, 3], 0)


if __name__ == "__main__":
    unittest.main()

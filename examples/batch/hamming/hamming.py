def hamming_distance(a: bytes, b: bytes) -> int:
    if len(a) != len(b):
        raise ValueError("Strings must have equal length")

    return sum(1 for x, y in zip(a, b) if x != y)

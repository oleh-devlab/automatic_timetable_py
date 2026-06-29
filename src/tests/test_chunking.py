import unittest
from chunking import calculate_chunks

class TestCalculateChunks(unittest.TestCase):
    def test_missing_min_or_max(self):
        """If min_chunk_duration or max_chunk_duration is None, should return 1."""
        self.assertEqual(calculate_chunks(100, None, 50), 1)
        self.assertEqual(calculate_chunks(100, 20, None), 1)
        self.assertEqual(calculate_chunks(100, None, None), 1)

    def test_duration_less_or_equal_min(self):
        """If duration is <= min_chunk_duration, it should return 1."""
        self.assertEqual(calculate_chunks(30, 30, 50), 1)
        self.assertEqual(calculate_chunks(20, 30, 50), 1)

    def test_duration_greater_than_min(self):
        """If duration > min_chunk_duration, should return math.ceil(duration / min_chunk_duration)."""
        self.assertEqual(calculate_chunks(100, 30, 50), 4) # 100/30 = 3.33 -> ceil = 4
        self.assertEqual(calculate_chunks(90, 30, 50), 3)  # 90/30 = 3.0 -> ceil = 3

    def test_exact_division(self):
        """Duration perfectly divided by max or min chunk should be handled cleanly."""
        self.assertEqual(calculate_chunks(100, 25, 50), 4)

    def test_fixed_chunk_size(self):
        """If min_chunk_duration == max_chunk_duration, it should still calculate normally."""
        self.assertEqual(calculate_chunks(90, 30, 30), 3)

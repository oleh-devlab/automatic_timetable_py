import unittest

from restrictions import calculate_horizon, generate_blocked_intervals
from data_structs import Task, TimeBlock

class TestCalculateHorizon(unittest.TestCase):
    def test_small_total_task_duration(self):
        """
        When base_horizon * 3 + 1440 is LESS than max_horizon_days * 1440,
        it should return max_horizon_days * 1440.
        """
        tasks_small = [
            Task(name="Task 1", duration=30),
            Task(name="Task 2", duration=30)
        ]
        # max_horizon_days = 14 -> 14 * 1440 = 20160
        # Total duration = 60 min. -> 60 * 3 + 1440 = 1620
        # max(1620, 20160) = 20160
        self.assertEqual(calculate_horizon(tasks_small, max_horizon_days=14), 20160)

    def test_large_total_task_duration(self):
        """
        When base_horizon * 3 + 1440 is GREATER than max_horizon_days * 1440,
        it should return base_horizon * 3 + 1440.
        """
        tasks_large = [
            Task(name="Task 1", duration=500),
            Task(name="Task 2", duration=500)
        ]
        # max_horizon_days = 2 -> 2 * 1440 = 2880
        # Total duration = 1000 min. -> 1000 * 3 + 1440 = 4440
        # max(4440, 2880) = 4440
        self.assertEqual(calculate_horizon(tasks_large, max_horizon_days=2), 4440)

    def test_empty_task_list(self):
        """
        When the task list is empty, it should correctly compute the horizon based on 0 duration.
        """
        # Total duration = 0 -> 0 * 3 + 1440 = 1440
        # max(1440, 1 * 1440) = 1440
        self.assertEqual(calculate_horizon([], max_horizon_days=1), 1440)

    def test_default_max_horizon_days(self):
        """
        When max_horizon_days is not provided, it should use the default value (14).
        """
        # 14 (default) * 1440 = 20160
        self.assertEqual(calculate_horizon([]), 20160)

    def test_invalid_max_horizon_days(self):
        """
        ValueError should be raised if max_horizon_days <= 0.
        """
        with self.assertRaises(ValueError):
            calculate_horizon([], max_horizon_days=0)
        with self.assertRaises(ValueError):
            calculate_horizon([], max_horizon_days=-5)

class TestGenerateBlockedIntervals(unittest.TestCase):
    def test_single_non_daily_block(self):
        """A single non-daily block should be returned as-is."""
        blocks = [TimeBlock(100, 200, daily=False)]
        result = generate_blocked_intervals(blocks, horizon=5000)
        self.assertEqual(result, [(100, 200)])

    def test_daily_block_cloning(self):
        """
        A daily block should be cloned every 1440 min until it exceeds the horizon.
        Block (60, 120) with horizon=3000 should produce:
          day 0: (60, 120), day 1: (1500, 1560), day 2: (2940, 3000)
          day 3: start=4380 >= 3000 -> stop
        """
        blocks = [TimeBlock(60, 120, daily=True)]
        result = generate_blocked_intervals(blocks, horizon=3000)
        self.assertEqual(result, [(60, 120), (1500, 1560), (2940, 3000)])

    def test_negative_start_clamped_to_zero(self):
        """
        When a block has a negative start (partially in the past),
        the start should be clamped to 0 while the end is preserved.
        """
        blocks = [TimeBlock(-30, 50, daily=False)]
        result = generate_blocked_intervals(blocks, horizon=5000)
        self.assertEqual(result, [(0, 50)])

    def test_entirely_in_the_past_block_is_dropped(self):
        """
        A non-daily block whose end <= 0 (entirely in the past) should be dropped.
        """
        blocks = [TimeBlock(-100, -10, daily=False)]
        result = generate_blocked_intervals(blocks, horizon=5000)
        self.assertEqual(result, [])

    def test_overlapping_blocks_are_merged(self):
        """
        Overlapping or adjacent blocks should be merged into one interval.
        (10, 100) and (80, 200) -> (10, 200)
        """
        blocks = [
            TimeBlock(10, 100, daily=False),
            TimeBlock(80, 200, daily=False),
        ]
        result = generate_blocked_intervals(blocks, horizon=5000)
        self.assertEqual(result, [(10, 200)])

    def test_empty_input(self):
        """No time blocks should produce an empty result."""
        result = generate_blocked_intervals([], horizon=5000)
        self.assertEqual(result, [])

    def test_block_ends_exactly_at_zero(self):
        """A non-daily block ending exactly at 0 is in the past and should be dropped."""
        blocks = [TimeBlock(-100, 0, daily=False)]
        result = generate_blocked_intervals(blocks, horizon=5000)
        self.assertEqual(result, [])

    def test_block_beyond_horizon_is_dropped(self):
        """A block starting at or after the horizon should not be included."""
        blocks = [TimeBlock(6000, 7000, daily=False)]
        result = generate_blocked_intervals(blocks, horizon=5000)
        self.assertEqual(result, [])

    def test_daily_block_with_negative_start(self):
        """
        A daily block starting in the past should clamp its first occurrence
        to 0 and correctly clone subsequent days.
        Block (-20, 40) daily, horizon=1500:
          clone 0: start=-20 -> clamped to 0, end=40  -> (0, 40)
          clone 1: start=1420, end=1480              -> (1420, 1480)
          clone 2: start=2860 >= 1500 -> stop
        """
        blocks = [TimeBlock(-20, 40, daily=True)]
        result = generate_blocked_intervals(blocks, horizon=1500)
        self.assertEqual(result, [(0, 40), (1420, 1480)])

    def test_mixed_daily_and_non_daily(self):
        """
        Tests a mix of daily and non-daily blocks in a single call.
        Non-daily (500, 600) stays as-is.
        Daily (0, 60) with horizon=1500 produces: (0, 60), (1440, 1500).
        Result should be sorted/merged.
        """
        blocks = [
            TimeBlock(500, 600, daily=False),
            TimeBlock(0, 60, daily=True),
        ]
        result = generate_blocked_intervals(blocks, horizon=1500)
        self.assertEqual(result, [(0, 60), (500, 600), (1440, 1500)])


if __name__ == '__main__':
    unittest.main()
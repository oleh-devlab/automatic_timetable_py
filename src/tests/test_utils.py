import unittest
from datetime import datetime, timedelta
import os

from utils import merge_time_blocks, minutes_to_time, process_time_blocks
from data_structs import TimeBlock

class TestMergeTimeBlocks(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(merge_time_blocks([]), [])

    def test_single_block(self):
        blocks = [TimeBlock(10, 20)]
        merged = merge_time_blocks(blocks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start, 10)
        self.assertEqual(merged[0].end, 20)

    def test_non_overlapping(self):
        blocks = [TimeBlock(10, 20), TimeBlock(30, 40)]
        merged = merge_time_blocks(blocks)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].start, 10)
        self.assertEqual(merged[0].end, 20)
        self.assertEqual(merged[1].start, 30)
        self.assertEqual(merged[1].end, 40)

    def test_overlapping(self):
        blocks = [TimeBlock(10, 30), TimeBlock(20, 40)]
        merged = merge_time_blocks(blocks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start, 10)
        self.assertEqual(merged[0].end, 40)

    def test_fully_contained(self):
        blocks = [TimeBlock(10, 50), TimeBlock(20, 30)]
        merged = merge_time_blocks(blocks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start, 10)
        self.assertEqual(merged[0].end, 50)

    def test_adjacent_blocks(self):
        blocks = [TimeBlock(10, 20), TimeBlock(20, 30)]
        merged = merge_time_blocks(blocks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start, 10)
        self.assertEqual(merged[0].end, 30)

    def test_multiple_merges_and_sorting(self):
        blocks = [
            TimeBlock(50, 60),
            TimeBlock(10, 30),
            TimeBlock(20, 40),
            TimeBlock(65, 75)
        ]
        merged = merge_time_blocks(blocks)
        self.assertEqual(len(merged), 3)
        self.assertEqual((merged[0].start, merged[0].end), (10, 40))
        self.assertEqual((merged[1].start, merged[1].end), (50, 60))
        self.assertEqual((merged[2].start, merged[2].end), (65, 75))


class TestMinutesToTime(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2023, 10, 25, 12, 0) # 12:00 PM

    def test_positive_minutes(self):
        self.assertEqual(minutes_to_time(60, self.now), self.now + timedelta(minutes=60))
        self.assertEqual(minutes_to_time(15, self.now), self.now + timedelta(minutes=15))

    def test_negative_minutes(self):
        self.assertEqual(minutes_to_time(-60, self.now), self.now + timedelta(minutes=-60))

    def test_zero_minutes(self):
        self.assertEqual(minutes_to_time(0, self.now), self.now)

    def test_cross_day(self):
        self.assertEqual(minutes_to_time(1440, self.now), self.now + timedelta(minutes=1440))


class TestProcessTimeBlocks(unittest.TestCase):
    def setUp(self):
        # "now" is 25.10.2023 12:00
        self.now = datetime(2023, 10, 25, 12, 0)

    def test_non_daily_future(self):
        raw = [TimeBlock("25.10.2023 13:00", "25.10.2023 14:00", daily=False)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, 60)
        self.assertEqual(blocks[0].end, 120)
        self.assertFalse(blocks[0].daily)

    def test_non_daily_past(self):
        raw = [TimeBlock("25.10.2023 10:00", "25.10.2023 11:00", daily=False)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 0)

    def test_non_daily_partially_past(self):
        raw = [TimeBlock("25.10.2023 11:30", "25.10.2023 12:30", daily=False)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, -30)
        self.assertEqual(blocks[0].end, 30)

    def test_daily_future_today(self):
        raw = [TimeBlock("25.10.2023 14:00", "25.10.2023 15:00", daily=True)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, 120)
        self.assertEqual(blocks[0].end, 180)
        self.assertTrue(blocks[0].daily)

    def test_daily_past_today(self):
        # Passed for today, so it should be scheduled for tomorrow
        raw = [TimeBlock("25.10.2023 09:00", "25.10.2023 10:00", daily=True)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        # Tomorrow is 1440 min away. 
        # Today it was at -180 min from now (12:00 -> 09:00 = 3h = 180m).
        # Tomorrow will be at 1440 - 180 = 1260
        # End is +60 from start
        self.assertEqual(blocks[0].start, 1260)
        self.assertEqual(blocks[0].end, 1320)
        self.assertTrue(blocks[0].daily)

    def test_daily_partially_past(self):
        # Started at 11:30, ends at 12:30. Now is 12:00.
        raw = [TimeBlock("25.10.2023 11:30", "25.10.2023 12:30", daily=True)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, -30)
        self.assertEqual(blocks[0].end, 30)
        self.assertTrue(blocks[0].daily)

    def test_daily_crosses_midnight(self):
        # 23:00 to 02:00. Now is 12:00
        raw = [TimeBlock("25.10.2023 23:00", "26.10.2023 02:00", daily=True)]
        # s = 23*60 = 1380. e = 2*60 = 120 -> e += 1440 = 1560
        # now_min = 12*60 = 720. 
        # start_rel = 1380 - 720 = 660
        # end_rel = 1560 - 720 = 840
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, 660)
        self.assertEqual(blocks[0].end, 840)
        self.assertTrue(blocks[0].daily)

    def test_start_greater_than_end_daily(self):
        """If daily=True and start time is later than end time, it implies crossing midnight."""
        raw = [TimeBlock("25.10.2023 15:00", "25.10.2023 14:00", daily=True)]
        blocks = process_time_blocks(raw, self.now)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].start, -1260)
        self.assertEqual(blocks[0].end, 120)
        self.assertTrue(blocks[0].daily)

    def test_invalid_date_format(self):
        """Should raise ValueError when the date format is invalid."""
        raw = [TimeBlock("2023/10/25 13-00", "2023/10/25 14-00", daily=True)]
        with self.assertRaises(ValueError):
            process_time_blocks(raw, self.now)

if __name__ == '__main__':
    unittest.main()

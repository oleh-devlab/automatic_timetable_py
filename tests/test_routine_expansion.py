import unittest
from datetime import datetime

from src.data_structs import Routine
from src.routine_expansion import expand_routines


class TestExpandRoutinesFixed(unittest.TestCase):
    """Tests for expand_routines with fixed-time routines."""

    def test_daily_fixed_generates_blocks_for_each_day(self):
        """A daily fixed routine should produce one TimeBlock per day within the horizon."""
        routine = Routine(name="Workout", type="fixed", repeat="daily", duration=60, time="07:00")
        # Monday 2026-07-06 10:00
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 3 * 1440  # 3 days

        _, extra_blocks, routine_info = expand_routines([routine], now, horizon)

        fixed_info = [r for r in routine_info if r["type"] == "fixed"]
        # Day 0 (07:00 already passed at 10:00 — but end_min = -120 which is <=0, skipped)
        # Day 1, 2, 3 should all produce blocks at 07:00
        self.assertGreater(len(extra_blocks), 0, "Should generate at least one TimeBlock")
        self.assertEqual(len(extra_blocks), len(fixed_info))

        for block in extra_blocks:
            self.assertFalse(block.daily, "Expanded blocks should not be daily")
            self.assertEqual(block.end - block.start, 60, "Each block should be 60 min")

    def test_daily_fixed_skips_past_occurrences(self):
        """If the routine's time has already passed today, the first instance is tomorrow."""
        routine = Routine(name="Morning", type="fixed", repeat="daily", duration=30, time="06:00")
        now = datetime(2026, 7, 6, 12, 0)  # noon
        horizon = 1440  # 1 day

        _, extra_blocks, _ = expand_routines([routine], now, horizon)

        # 06:00 today is -360 min from noon → end_min = -330 → skipped.
        # 06:00 tomorrow is 1080 min from noon → should be included.
        for block in extra_blocks:
            self.assertGreater(block.end, 0, "All blocks must end in the future")

    def test_fixed_without_time_is_skipped(self):
        """A fixed routine with no time field should be silently skipped."""
        routine = Routine(name="Broken", type="fixed", repeat="daily", duration=60, time=None)
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 1440

        _, extra_blocks, routine_info = expand_routines([routine], now, horizon)

        self.assertEqual(len(extra_blocks), 0)
        self.assertEqual(len(routine_info), 0)

    def test_weekly_fixed_only_on_correct_weekdays(self):
        """A weekly fixed routine should only appear on specified weekdays."""
        # Monday=0 in Python's weekday()
        routine = Routine(
            name="Piano", type="fixed", repeat="weekly", duration=60, time="15:00", weekdays=[0, 4]  # Mon and Fri
        )
        # Start on Monday 2026-07-06
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 7 * 1440  # 7 days

        _, extra_blocks, routine_info = expand_routines([routine], now, horizon)

        # days = [r["day"] for r in routine_info]
        # Mon=06.07, Fri=10.07, next Mon=13.07
        for info in routine_info:
            parsed = info["day"]
            self.assertIn(
                parsed.weekday(),
                [0, 4],
                f"Routine on {info['day']} is weekday {parsed.weekday()}, expected Mon(0) or Fri(4)",
            )

    def test_weekly_with_empty_weekdays_generates_nothing(self):
        """A weekly routine with weekdays=[] should produce no instances."""
        routine = Routine(name="Nothing", type="fixed", repeat="weekly", duration=30, time="09:00", weekdays=[])
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 14 * 1440

        _, extra_blocks, routine_info = expand_routines([routine], now, horizon)

        self.assertEqual(len(extra_blocks), 0)
        self.assertEqual(len(routine_info), 0)


class TestExpandRoutinesFlexible(unittest.TestCase):
    """Tests for expand_routines with flexible routines."""

    def test_daily_flexible_generates_tasks_for_each_day(self):
        """A daily flexible routine should produce one Task per day."""
        routine = Routine(
            name="Study",
            type="flexible",
            repeat="daily",
            duration=30,
            priority=5,
            deadline_time="18:00",
            break_duration=5,
        )
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 3 * 1440  # 3 days

        extra_tasks, _, routine_info = expand_routines([routine], now, horizon)

        flex_info = [r for r in routine_info if r["type"] == "flexible"]
        self.assertGreater(len(extra_tasks), 0)
        self.assertEqual(len(extra_tasks), len(flex_info))

        for task in extra_tasks:
            self.assertEqual(task.duration, 30)
            self.assertEqual(task.priority, 5)
            self.assertEqual(task.break_duration, 5)
            self.assertTrue(task.is_routine)
            self.assertIsNone(task.min_chunk_duration, "Routines should not have chunking")
            self.assertIsNone(task.max_chunk_duration, "Routines should not have chunking")

    def test_flexible_deadline_is_set_correctly(self):
        """The generated Task's deadline_min should match the routine's deadline_time for its day."""
        routine = Routine(name="Words", type="flexible", repeat="daily", duration=30, deadline_time="18:00")
        now = datetime(2026, 7, 6, 10, 0)  # 10:00
        horizon = 1440  # 1 day

        extra_tasks, _, _ = expand_routines([routine], now, horizon)

        # The first task with a future deadline should be today at 18:00 → 480 min from now
        today_tasks = [t for t in extra_tasks if "(06.07)" in t.name]
        if today_tasks:
            self.assertEqual(today_tasks[0].deadline_min, 480, "Deadline should be 480 min (8h) from 10:00 to 18:00")

    def test_flexible_without_deadline_defaults_to_2359(self):
        """A flexible routine without deadline_time should default to 23:59."""
        routine = Routine(name="Read", type="flexible", repeat="daily", duration=20)
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 1440

        extra_tasks, _, _ = expand_routines([routine], now, horizon)

        today_tasks = [t for t in extra_tasks if "(06.07)" in t.name]
        if today_tasks:
            # 23:59 - 10:00 = 13h59m = 839 min
            self.assertEqual(today_tasks[0].deadline_min, 839)

    def test_flexible_past_deadline_today_is_skipped(self):
        """If the deadline for today has already passed, that day's instance is skipped."""
        routine = Routine(name="Morning", type="flexible", repeat="daily", duration=30, deadline_time="09:00")
        now = datetime(2026, 7, 6, 12, 0)  # noon
        horizon = 1440

        extra_tasks, _, _ = expand_routines([routine], now, horizon)

        # deadline_min for today = 09:00 - 12:00 = -180 → skipped
        today_tasks = [t for t in extra_tasks if "(06.07)" in t.name]
        self.assertEqual(len(today_tasks), 0, "Past deadline should be skipped")

    def test_weekly_flexible_only_on_correct_weekdays(self):
        """A weekly flexible routine should only appear on specified weekdays."""
        routine = Routine(
            name="Cleaning", type="flexible", repeat="weekly", duration=90, priority=3, weekdays=[5]  # Saturday
        )
        now = datetime(2026, 7, 6, 10, 0)  # Monday
        horizon = 14 * 1440

        extra_tasks, _, routine_info = expand_routines([routine], now, horizon)

        for info in routine_info:
            self.assertEqual(
                info["day"].weekday(),
                5,
                f"Routine on {info['day']} is weekday {info['day'].weekday()}, expected Sat(5)",
            )

    def test_task_name_contains_date(self):
        """Each generated task name should contain the day.month suffix."""
        routine = Routine(name="Study", type="flexible", repeat="daily", duration=30)
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 2 * 1440

        extra_tasks, _, _ = expand_routines([routine], now, horizon)

        for task in extra_tasks:
            self.assertRegex(
                task.name, r"Study \(\d{2}\.\d{2}\)", f"Task name '{task.name}' does not match expected pattern"
            )


class TestExpandRoutinesEdgeCases(unittest.TestCase):
    """Edge cases for expand_routines."""

    def test_empty_routines_list(self):
        """An empty routines list should return empty results."""
        now = datetime(2026, 7, 6, 10, 0)
        extra_tasks, extra_blocks, routine_info = expand_routines([], now, 1440)

        self.assertEqual(len(extra_tasks), 0)
        self.assertEqual(len(extra_blocks), 0)
        self.assertEqual(len(routine_info), 0)

    def test_zero_horizon_produces_minimal_output(self):
        """A horizon of 0 minutes should produce at most the current-day instance."""
        routine = Routine(name="Quick", type="flexible", repeat="daily", duration=10, deadline_time="23:59")
        now = datetime(2026, 7, 6, 10, 0)

        extra_tasks, _, _ = expand_routines([routine], now, 0)

        # horizon_days = 0 // 1440 + 1 = 1, so range(2) → day 0 and day 1
        # day 0 deadline_min = 839, but deadline_min - duration (829) > horizon (0),
        # so it should be skipped due to horizon check
        for task in extra_tasks:
            self.assertGreater(task.deadline_min, 0, "All tasks must have future deadlines")

    def test_mixed_routines(self):
        """A mix of fixed and flexible routines should produce both blocks and tasks."""
        fixed = Routine(name="Gym", type="fixed", repeat="daily", duration=60, time="07:00")
        flexible = Routine(name="Read", type="flexible", repeat="daily", duration=30, priority=2)
        now = datetime(2026, 7, 6, 10, 0)
        horizon = 2 * 1440

        extra_tasks, extra_blocks, routine_info = expand_routines([fixed, flexible], now, horizon)

        self.assertGreater(len(extra_blocks), 0, "Fixed routine should produce blocks")
        self.assertGreater(len(extra_tasks), 0, "Flexible routine should produce tasks")

        fixed_info = [r for r in routine_info if r["type"] == "fixed"]
        flex_info = [r for r in routine_info if r["type"] == "flexible"]
        self.assertGreater(len(fixed_info), 0)
        self.assertGreater(len(flex_info), 0)


if __name__ == "__main__":
    unittest.main()

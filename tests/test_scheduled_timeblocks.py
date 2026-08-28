import unittest
from datetime import datetime, time, timedelta
from unittest.mock import patch

from ortools.sat.python import cp_model

from src.data_structs import Routine, Task, TimeBlock
from src.scheduler import ScheduledTimeBlock, Scheduler, _expand_timeblocks_for_export


class TestExpandTimeblocksForExport(unittest.TestCase):
    """Tests for _expand_timeblocks_for_export() — the export-only expansion function."""

    def setUp(self):
        self.now = datetime(2026, 7, 17, 10, 0)
        self.step_minutes = 1

    # --- Basic expansion ---

    def test_single_non_daily_block(self):
        """A single non-daily block should produce one ScheduledTimeBlock."""
        blocks = [TimeBlock(start=60, end=120, daily=False, name="Lunch")]
        result = _expand_timeblocks_for_export(blocks, horizon=1440, now=self.now, step_minutes=self.step_minutes)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Lunch")
        self.assertEqual(result[0].start_time, self.now + timedelta(minutes=60))
        self.assertEqual(result[0].end_time, self.now + timedelta(minutes=120))

    def test_daily_block_expansion(self):
        """A daily block should clone across multiple days within the horizon."""
        # Block at offset 60..120, daily=True, horizon covers ~2 days
        blocks = [TimeBlock(start=60, end=120, daily=True, name="Morning Coffee")]
        horizon = 1440 * 2  # 2 days = 2880 steps

        result = _expand_timeblocks_for_export(blocks, horizon=horizon, now=self.now, step_minutes=self.step_minutes)

        # day 0: 60..120, day 1: 1500..1560
        # day 2: start=2940 >= 2880 -> stop
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].start_time, self.now + timedelta(minutes=60))
        self.assertEqual(result[0].end_time, self.now + timedelta(minutes=120))
        self.assertEqual(result[1].start_time, self.now + timedelta(minutes=1500))
        self.assertEqual(result[1].end_time, self.now + timedelta(minutes=1560))

    # --- Unmerged identities ---

    def test_overlapping_blocks_preserved_individually(self):
        """
        Two overlapping blocks must NOT be merged — each retains its identity.
        E.g. Workout 17:00-18:30 and Commute 18:15-19:00 overlap but stay separate.
        """
        workout = TimeBlock(start=100, end=190, daily=False, name="Workout")
        commute = TimeBlock(start=175, end=240, daily=False, name="Commute")

        result = _expand_timeblocks_for_export(
            [workout, commute], horizon=1440, now=self.now, step_minutes=self.step_minutes
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, "Workout")
        self.assertEqual(result[1].name, "Commute")
        # Verify exact boundaries are preserved (not merged into one 100..240)
        self.assertEqual(result[0].end_time, self.now + timedelta(minutes=190))
        self.assertEqual(result[1].start_time, self.now + timedelta(minutes=175))

    # --- True datetime boundaries (no clamping) ---

    def test_past_start_preserved(self):
        """
        A block whose start is before 'now' (negative offset) must retain
        its true start_time in the past, NOT clamped to now.
        E.g. Sleep block started 30 min ago.
        """
        blocks = [TimeBlock(start=-30, end=50, daily=False, name="Sleep")]
        result = _expand_timeblocks_for_export(blocks, horizon=1440, now=self.now, step_minutes=self.step_minutes)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Sleep")
        # start_time should be 30 minutes BEFORE now
        self.assertEqual(result[0].start_time, self.now - timedelta(minutes=30))
        self.assertEqual(result[0].end_time, self.now + timedelta(minutes=50))

    def test_daily_block_past_start_preserved(self):
        """
        A daily block whose first occurrence starts before now
        should have its true start_time in the past.
        """
        blocks = [TimeBlock(start=-20, end=40, daily=True, name="Night Routine")]
        result = _expand_timeblocks_for_export(blocks, horizon=1500, now=self.now, step_minutes=self.step_minutes)

        # day 0: -20..40 (partially past, end > 0 -> included)
        # day 1: 1420..1480 (within horizon)
        # day 2: start=2860 >= 1500 -> stop
        self.assertEqual(len(result), 2)
        # First occurrence preserves the past start
        self.assertEqual(result[0].start_time, self.now - timedelta(minutes=20))
        self.assertEqual(result[0].end_time, self.now + timedelta(minutes=40))

    # --- Filtering ---

    def test_entirely_past_block_filtered_out(self):
        """A non-daily block entirely in the past (end <= 0) is not included."""
        blocks = [TimeBlock(start=-100, end=-10, daily=False, name="Gone")]
        result = _expand_timeblocks_for_export(blocks, horizon=1440, now=self.now, step_minutes=self.step_minutes)
        self.assertEqual(result, [])

    def test_block_beyond_horizon_filtered(self):
        """A non-daily block starting at or after the horizon is not included."""
        blocks = [TimeBlock(start=5000, end=6000, daily=False, name="Far Future")]
        result = _expand_timeblocks_for_export(blocks, horizon=3000, now=self.now, step_minutes=self.step_minutes)
        self.assertEqual(result, [])

    def test_empty_input(self):
        """No blocks produces an empty result."""
        result = _expand_timeblocks_for_export([], horizon=1440, now=self.now, step_minutes=self.step_minutes)
        self.assertEqual(result, [])

    # --- Name handling ---

    def test_empty_name_backward_compatible(self):
        """Blocks without a name get an empty string — backward compatible."""
        blocks = [TimeBlock(start=10, end=50, daily=False)]
        result = _expand_timeblocks_for_export(blocks, horizon=1440, now=self.now, step_minutes=self.step_minutes)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "")

    # --- step_minutes > 1 ---

    def test_step_minutes_scaling(self):
        """When step_minutes > 1, offsets are correctly scaled to real minutes."""
        blocks = [TimeBlock(start=10, end=20, daily=False, name="Quick")]
        # step_minutes=5 -> real start = 50 min, real end = 100 min
        result = _expand_timeblocks_for_export(blocks, horizon=300, now=self.now, step_minutes=5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].start_time, self.now + timedelta(minutes=50))
        self.assertEqual(result[0].end_time, self.now + timedelta(minutes=100))


class TestFixedRoutinesAreNotExportedTwice(unittest.TestCase):
    """A fixed routine reaches the client once, as a ScheduledRoutine — never also as a time block."""

    NOW = datetime(2026, 7, 6, 10, 0)  # Monday

    def _solve(self, routines=(), blocks=(), tasks=(), **kwargs):
        scheduler = Scheduler(min_horizon_days=2, priority_threshold=5, step_minutes=5)
        for routine in routines:
            scheduler.add_routine(routine)
        for block in blocks:
            scheduler.add_time_block(block)
        for task in tasks:
            scheduler.add_task(task)
        return scheduler.solve(start_time=self.NOW, **kwargs)

    def _lecture(self):
        return Routine(
            name="Lecture",
            type="fixed",
            repeat="daily",
            duration=timedelta(minutes=90),
            time=time(14, 0),
            id=7,
        )

    def test_fixed_routine_absent_from_scheduled_timeblocks(self):
        result = self._solve(routines=[self._lecture()])

        self.assertTrue(result.is_successful)
        self.assertEqual([b for b in result.scheduled_timeblocks if b.name == "Lecture"], [])

    def test_fixed_routine_still_exported_as_a_routine(self):
        result = self._solve(routines=[self._lecture()])

        lectures = [r for r in result.scheduled_routines if r.task.name == "Lecture"]
        self.assertTrue(lectures)
        self.assertTrue(all(r.routine_type == "fixed" and r.routine_id == 7 for r in lectures))
        # Exact calendar bounds, not step-rounded ones
        first = min(lectures, key=lambda r: r.start_time)
        self.assertEqual(first.start_time, datetime(2026, 7, 6, 14, 0))
        self.assertEqual(first.end_time, datetime(2026, 7, 6, 15, 30))

    def test_user_time_blocks_are_still_exported(self):
        """Dropping routine-derived blocks must not take the user's own blocks with them."""
        lunch = TimeBlock(start=datetime(2020, 1, 1, 12, 0), end=datetime(2020, 1, 1, 13, 0), daily=True, name="Lunch")

        result = self._solve(routines=[self._lecture()], blocks=[lunch])

        self.assertEqual({b.name for b in result.scheduled_timeblocks}, {"Lunch"})

    def test_nothing_is_exported_when_the_solve_fails(self):
        """A failed solve yields no schedule at all — time blocks included."""
        lunch = TimeBlock(start=datetime(2020, 1, 1, 12, 0), end=datetime(2020, 1, 1, 13, 0), daily=True, name="Lunch")
        task = Task(name="Homework", duration=timedelta(minutes=30), priority=5)

        # Every task is optional, so the model itself is always satisfiable; only a solver that
        # returns no solution (timeout, memory limit) can drive the unsuccessful path.
        with patch.object(cp_model.CpSolver, "solve", return_value=cp_model.INFEASIBLE):
            result = self._solve(blocks=[lunch], tasks=[task])

        self.assertFalse(result.is_successful)
        self.assertEqual(result.scheduled_timeblocks, [])
        self.assertEqual(result.scheduled_tasks, [])
        self.assertEqual(result.scheduled_routines, [])


class TestScheduledTimeBlockDataclass(unittest.TestCase):
    """Basic tests for the ScheduledTimeBlock dataclass itself."""

    def test_fields(self):
        now = datetime(2026, 7, 17, 10, 0)
        stb = ScheduledTimeBlock(name="Gym", start_time=now, end_time=now + timedelta(hours=1))
        self.assertEqual(stb.name, "Gym")
        self.assertEqual(stb.start_time, now)
        self.assertEqual(stb.end_time, now + timedelta(hours=1))


class TestTimeBlockNameField(unittest.TestCase):
    """Tests that the name field on TimeBlock works correctly."""

    def test_default_name_is_empty(self):
        tb = TimeBlock(start=0, end=100)
        self.assertEqual(tb.name, "")

    def test_name_field_set(self):
        tb = TimeBlock(start=0, end=100, name="Sleep")
        self.assertEqual(tb.name, "Sleep")

    def test_backward_compatible_positional(self):
        """Existing positional calls still work."""
        tb = TimeBlock(0, 100)
        self.assertEqual(tb.start, 0)
        self.assertEqual(tb.end, 100)
        self.assertTrue(tb.daily)
        self.assertEqual(tb.name, "")

    def test_backward_compatible_with_daily(self):
        """Existing calls with daily keyword still work."""
        tb = TimeBlock(0, 100, daily=False)
        self.assertFalse(tb.daily)
        self.assertEqual(tb.name, "")


if __name__ == "__main__":
    unittest.main()

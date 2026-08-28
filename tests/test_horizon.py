import math
import unittest
from datetime import datetime, timedelta

from src.data_structs import Task, TimeBlock
from src.restrictions import calculate_horizon
from src.scheduler import Scheduler
from src.utils import process_time_blocks

NOW = datetime(2026, 7, 6, 8, 0)
STEP = 5
STEPS_PER_DAY = 1440 // STEP


def _tight_calendar():
    """Ordinary but dense calendar leaving 4 free hours a day (07:00-09:00, 21:00-23:00)."""
    return [
        TimeBlock(start=datetime(2026, 7, 6, 23, 0), end=datetime(2026, 7, 7, 7, 0), daily=True, name="sleep"),
        TimeBlock(start=datetime(2026, 7, 6, 9, 0), end=datetime(2026, 7, 6, 18, 0), daily=True, name="job"),
        TimeBlock(start=datetime(2026, 7, 6, 18, 0), end=datetime(2026, 7, 6, 21, 0), daily=True, name="evening"),
    ]


class TestHorizonCoversScarceFreeTime(unittest.TestCase):
    """
    calculate_horizon() bounds its free-window universe by `base_horizon * 3`, which silently
    assumes at most two thirds of every day is blocked. Denser calendars make the simulation
    unable to discover that it needs more days, so the horizon comes out too short and the
    solver drops tasks that are perfectly schedulable.
    """

    def test_no_task_is_skipped_for_lack_of_horizon(self):
        """12 two-hour tasks into 4 free hours a day need ~6 days; none of them may be skipped."""
        scheduler = Scheduler(min_horizon_days=3, priority_threshold=5, step_minutes=STEP)
        for i in range(12):
            scheduler.add_task(Task(name=f"t{i}", duration=timedelta(minutes=120), priority=3, id=f"t{i}"))
        for block in _tight_calendar():
            scheduler.add_time_block(block)

        result = scheduler.solve(start_time=NOW, timeouts={"packer": 10.0, "gravity": 5.0}, num_search_workers=8)

        self.assertTrue(result.is_successful)
        skipped = sorted(s.task.name for s in result.skipped_tasks)
        self.assertEqual(skipped, [], f"tasks dropped only because the horizon was too short: {skipped}")

    def test_horizon_reaches_the_time_the_work_actually_needs(self):
        """
        Unit-level check on calculate_horizon itself: with 3 free hours a day (20:00-23:00)
        exactly one two-hour task fits per day, so 8 tasks cannot finish inside 3 days.
        """
        tasks = [Task(name=f"t{i}", duration=timedelta(minutes=120), priority=3, id=f"t{i}") for i in range(8)]
        for task in tasks:
            task.duration_steps = math.ceil(task.duration.total_seconds() / 60 / STEP)
            task.break_duration_steps = 0

        blocks = process_time_blocks(
            [TimeBlock(start=datetime(2026, 7, 6, 23, 0), end=datetime(2026, 7, 7, 20, 0), daily=True, name="busy")],
            NOW,
            STEP,
        )

        horizon = calculate_horizon(tasks, blocks, min_horizon_days=3, step_minutes=STEP)

        # The eighth task can only take the eighth evening window, so the plan has to reach into
        # day 7 -- well past the three-day floor the old bound used to stop at.
        self.assertGreaterEqual(
            horizon,
            7 * STEPS_PER_DAY,
            f"horizon {horizon / STEPS_PER_DAY:.2f}d is too short for work that needs eight evenings",
        )
        self.assertLessEqual(
            horizon,
            9 * STEPS_PER_DAY,
            f"horizon {horizon / STEPS_PER_DAY:.2f}d overshoots what the work actually needs",
        )


class TestHorizonNotInflatedByFarDeadline(unittest.TestCase):
    """
    calculate_horizon() returns max(..., max_deadline). A deadline is an upper bound on when a
    task may be placed, not a requirement that the plan stretch that far, so a single distant
    deadline used to inflate the horizon (and every variable domain with it) enormously.
    """

    def test_single_far_deadline_does_not_stretch_the_plan(self):
        """Ten hours of work stay a few days of plan even when one task is due in 180 days."""
        scheduler = Scheduler(min_horizon_days=3, priority_threshold=5, step_minutes=STEP)
        for i in range(5):
            scheduler.add_task(Task(name=f"t{i}", duration=timedelta(minutes=120), priority=3, id=f"t{i}"))
        scheduler.add_task(
            Task(
                name="far",
                duration=timedelta(minutes=60),
                priority=3,
                id="far",
                deadline=NOW + timedelta(days=180),
            )
        )
        scheduler.add_time_block(
            TimeBlock(start=datetime(2026, 7, 6, 23, 0), end=datetime(2026, 7, 7, 7, 0), daily=True, name="sleep")
        )

        result = scheduler.solve(start_time=NOW, timeouts={"packer": 10.0, "gravity": 5.0}, num_search_workers=8)

        self.assertTrue(result.is_successful)
        self.assertEqual(len(result.skipped_tasks), 0)
        horizon_days = result.horizon / 60 / 24
        self.assertLessEqual(
            horizon_days,
            14,
            f"horizon blown up to {horizon_days:.0f} days by one distant deadline",
        )


class TestHorizonSeesPreExpandedOccurrences(unittest.TestCase):
    """
    A daily block is a template that clones itself to whatever bound the simulation grows to.
    Weekly blocks are materialised into a finite list of occurrences up front, so if that list
    stops short of the explored stretch the simulation reads the remainder as free time and
    settles on a horizon that is too short.
    """

    def _weekly_calendar(self):
        """The same calendar as _tight_calendar(), written as weekly blocks on every weekday."""
        every_day = [0, 1, 2, 3, 4, 5, 6]
        return [
            TimeBlock(datetime(2026, 7, 6, 23, 0), datetime(2026, 7, 7, 7, 0), name="sleep", weekdays=every_day),
            TimeBlock(datetime(2026, 7, 6, 9, 0), datetime(2026, 7, 6, 18, 0), name="job", weekdays=every_day),
            TimeBlock(datetime(2026, 7, 6, 18, 0), datetime(2026, 7, 6, 21, 0), name="evening", weekdays=every_day),
        ]

    def _solve(self, blocks):
        scheduler = Scheduler(min_horizon_days=3, priority_threshold=5, step_minutes=STEP)
        for i in range(12):
            scheduler.add_task(Task(name=f"t{i}", duration=timedelta(minutes=120), priority=3, id=f"t{i}"))
        for block in blocks:
            scheduler.add_time_block(block)
        return scheduler.solve(start_time=NOW, timeouts={"packer": 10.0, "gravity": 5.0}, num_search_workers=8)

    def test_weekly_blocks_do_not_shorten_the_horizon(self):
        """12 two-hour tasks into 4 free hours a day need ~6 days, whichever way the block is written."""
        result = self._solve(self._weekly_calendar())

        skipped = sorted(s.task.name for s in result.skipped_tasks)
        self.assertEqual(skipped, [], f"tasks dropped because weekly blocks ran out mid-simulation: {skipped}")

    def test_weekly_and_daily_calendars_agree(self):
        """The same busy hours expressed either way must produce the same plan."""
        weekly = self._solve(self._weekly_calendar())
        daily = self._solve(_tight_calendar())

        self.assertEqual(weekly.horizon, daily.horizon)
        self.assertEqual(len(weekly.scheduled_tasks), len(daily.scheduled_tasks))


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime, timedelta

from src.data_structs import Task, TimeBlock
from src.scheduler import Scheduler
from src.utils import expand_time_blocks, iter_active_dates, process_time_blocks

# 2026-07-06 is a Monday, so weekday indices map to dates as:
# Mon 06.07 / Tue 07.07 / Wed 08.07 / Thu 09.07 / Fri 10.07 / Sat 11.07 / Sun 12.07
MONDAY_10AM = datetime(2026, 7, 6, 10, 0)


def _block(start, end, weekdays, name="", id=None):
    """Build a weekly TimeBlock. Only the time-of-day part of start/end matters."""
    return TimeBlock(start=start, end=end, name=name, id=id, weekdays=weekdays)


class TestIterActiveDates(unittest.TestCase):
    """Tests for the shared calendar iterator behind routine and time block expansion."""

    def test_yields_every_day_when_no_weekdays(self):
        dates = list(iter_active_dates(MONDAY_10AM, 3 * 1440))
        self.assertEqual(dates[0], MONDAY_10AM.date())
        # Consecutive days, no gaps
        for earlier, later in zip(dates, dates[1:]):
            self.assertEqual((later - earlier).days, 1)

    def test_filters_by_weekday(self):
        dates = list(iter_active_dates(MONDAY_10AM, 14 * 1440, weekdays=[2, 4]))
        self.assertTrue(all(d.weekday() in (2, 4) for d in dates))
        self.assertIn(datetime(2026, 7, 8).date(), dates)  # Wednesday
        self.assertIn(datetime(2026, 7, 10).date(), dates)  # Friday

    def test_empty_weekdays_yields_nothing(self):
        self.assertEqual(list(iter_active_dates(MONDAY_10AM, 14 * 1440, weekdays=[])), [])

    def test_start_day_offset_includes_yesterday(self):
        dates = list(iter_active_dates(MONDAY_10AM, 1440, start_day_offset=-1))
        self.assertEqual(dates[0], datetime(2026, 7, 5).date())

    def test_scales_with_step_minutes(self):
        """horizon_minutes is in steps, so a coarser step covers the same span with fewer steps."""
        fine = list(iter_active_dates(MONDAY_10AM, 3 * 1440, step_minutes=1))
        coarse = list(iter_active_dates(MONDAY_10AM, 3 * (1440 // 5), step_minutes=5))
        self.assertEqual(fine, coarse)


class TestExpandTimeBlocks(unittest.TestCase):
    """Tests for expand_time_blocks() — weekly blocks -> concrete one-off occurrences."""

    # --- Basic expansion ---

    def test_weekly_block_expands_to_matching_weekdays(self):
        """A Wednesday block should produce one occurrence per Wednesday inside the horizon."""
        block = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 30), [2], name="Lecture")

        result = expand_time_blocks([block], MONDAY_10AM, 14 * 1440)

        # Wed 08.07 is 2 days + 4h away; the next one is 7 days later
        self.assertEqual([(b.start, b.end) for b in result], [(3120, 3210), (13200, 13290)])

    def test_multiple_weekdays(self):
        block = _block(datetime(2020, 1, 1, 9, 0), datetime(2020, 1, 1, 10, 0), [0, 3])

        result = expand_time_blocks([block], MONDAY_10AM, 7 * 1440)

        # Mon 06.07 09:00 already passed at 10:00 -> dropped; Thu 09.07, Mon 13.07 remain
        self.assertEqual([b.start for b in result], [3 * 1440 - 60, 7 * 1440 - 60])

    def test_occurrences_are_plain_non_daily_blocks(self):
        """Downstream code must see ordinary one-off blocks, not recurrence rules."""
        block = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 0), [2], name="Gym", id=7)

        for occurrence in expand_time_blocks([block], MONDAY_10AM, 14 * 1440):
            self.assertFalse(occurrence.daily)
            self.assertIsNone(occurrence.weekdays)
            self.assertEqual(occurrence.name, "Gym")
            self.assertEqual(occurrence.id, 7)

    def test_date_part_of_bounds_is_a_template(self):
        """Only the time of day matters — the date the user wrote is irrelevant."""
        old = _block(datetime(1999, 3, 15, 14, 0), datetime(1999, 3, 15, 15, 0), [2])
        future = _block(datetime(2031, 12, 24, 14, 0), datetime(2031, 12, 24, 15, 0), [2])

        self.assertEqual(
            [(b.start, b.end) for b in expand_time_blocks([old], MONDAY_10AM, 14 * 1440)],
            [(b.start, b.end) for b in expand_time_blocks([future], MONDAY_10AM, 14 * 1440)],
        )

    # --- Midnight crossing ---

    def test_block_crossing_midnight_is_anchored_on_its_start_weekday(self):
        """Friday 23:00-07:00 belongs to Friday and runs 8 hours into Saturday."""
        block = _block(datetime(2020, 1, 1, 23, 0), datetime(2020, 1, 1, 7, 0), [4], name="Sleep")

        result = expand_time_blocks([block], MONDAY_10AM, 7 * 1440)

        # Fri 10.07 23:00 is 4 days + 13h from Mon 10:00
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].start, 4 * 1440 + 13 * 60)
        self.assertEqual(result[0].end - result[0].start, 8 * 60)

    def test_occurrence_started_yesterday_and_still_running_is_kept(self):
        """At Saturday 02:00 the Friday-night block is half over, not gone."""
        block = _block(datetime(2020, 1, 1, 23, 0), datetime(2020, 1, 1, 7, 0), [4], name="Sleep")
        saturday_2am = datetime(2026, 7, 11, 2, 0)

        result = expand_time_blocks([block], saturday_2am, 7 * 1440)

        self.assertEqual(result[0].start, -180)  # started 3h ago
        self.assertEqual(result[0].end, 300)  # ends in 5h

    # --- Filtering ---

    def test_fully_past_occurrence_is_dropped(self):
        """At Saturday 10:00 the Friday-night block has ended and must not be emitted."""
        block = _block(datetime(2020, 1, 1, 23, 0), datetime(2020, 1, 1, 7, 0), [4])
        saturday_10am = datetime(2026, 7, 11, 10, 0)

        result = expand_time_blocks([block], saturday_10am, 14 * 1440)

        self.assertTrue(all(b.end > 0 for b in result))
        self.assertEqual(result[0].start, 6 * 1440 + 13 * 60)  # next Friday 23:00

    def test_occurrences_beyond_horizon_are_dropped(self):
        """With a one-day horizon, a Wednesday block from Monday produces nothing."""
        block = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 30), [2])

        self.assertEqual(expand_time_blocks([block], MONDAY_10AM, 1440), [])

    def test_non_weekly_blocks_are_ignored(self):
        """Blocks without weekdays belong to process_time_blocks(), not here."""
        daily = TimeBlock(start=datetime(2020, 1, 1, 14, 0), end=datetime(2020, 1, 1, 15, 0), daily=True)
        one_off = TimeBlock(start=datetime(2026, 7, 8, 14, 0), end=datetime(2026, 7, 8, 15, 0), daily=False)
        empty_weekdays = TimeBlock(start=datetime(2020, 1, 1, 14, 0), end=datetime(2020, 1, 1, 15, 0), weekdays=[])

        self.assertEqual(expand_time_blocks([daily, one_off, empty_weekdays], MONDAY_10AM, 14 * 1440), [])

    def test_already_expanded_blocks_are_ignored(self):
        """Step-offset blocks carry no calendar information, so there is nothing to expand."""
        already_steps = TimeBlock(start=60, end=120, daily=False, weekdays=[2])

        self.assertEqual(expand_time_blocks([already_steps], MONDAY_10AM, 14 * 1440), [])

    # --- Granularity ---

    def test_expansion_scales_with_step_minutes(self):
        block = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 30), [2])

        result = expand_time_blocks([block], MONDAY_10AM, 14 * (1440 // 5), step_minutes=5)

        self.assertEqual([(b.start, b.end) for b in result], [(624, 642), (2640, 2658)])

    def test_bounds_are_rounded_outwards(self):
        """Start floors and end ceils, so a coarse grid never under-blocks the interval."""
        block = _block(datetime(2020, 1, 1, 14, 2), datetime(2020, 1, 1, 15, 3), [2])

        first = expand_time_blocks([block], MONDAY_10AM, 14 * (1440 // 5), step_minutes=5)[0]

        self.assertEqual(first.start * 5, 3120)  # 14:02 floored to 14:00
        self.assertEqual(first.end * 5, 3185)  # 15:03 ceiled to 15:05


class TestProcessTimeBlocksSkipsWeekly(unittest.TestCase):
    """process_time_blocks() must leave weekly blocks alone so they are not counted twice."""

    def test_weekly_block_is_skipped(self):
        weekly = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 0), [2])

        self.assertEqual(process_time_blocks([weekly], MONDAY_10AM), [])

    def test_other_blocks_still_processed(self):
        weekly = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 0), [2])
        daily = TimeBlock(start=datetime(2020, 1, 1, 14, 0), end=datetime(2020, 1, 1, 15, 0), daily=True, name="Lunch")

        result = process_time_blocks([weekly, daily], MONDAY_10AM)

        self.assertEqual([b.name for b in result], ["Lunch"])


class TestTimeBlockValidation(unittest.TestCase):
    def test_weekday_out_of_range_raises(self):
        for bad in (-1, 7):
            with self.assertRaises(ValueError):
                TimeBlock(start=datetime(2020, 1, 1, 14, 0), end=datetime(2020, 1, 1, 15, 0), weekdays=[bad])

    def test_valid_weekdays_accepted(self):
        block = TimeBlock(start=datetime(2020, 1, 1, 14, 0), end=datetime(2020, 1, 1, 15, 0), weekdays=[0, 6])
        self.assertEqual(block.weekdays, [0, 6])


class TestWeeklyBlocksThroughScheduler(unittest.TestCase):
    """End-to-end: weekly blocks must block solver time and reach the client output."""

    def _scheduler(self, blocks, tasks=()):
        scheduler = Scheduler(min_horizon_days=2, priority_threshold=5, step_minutes=5)
        for block in blocks:
            scheduler.add_time_block(block)
        for task in tasks:
            scheduler.add_task(task)
        return scheduler

    def test_weekly_block_reserves_time_in_the_model(self):
        """With every day blocked 00:00-23:00, the only place left for a task is the late evening."""
        busy = _block(datetime(2020, 1, 1, 0, 0), datetime(2020, 1, 1, 23, 0), [0, 1, 2, 3, 4, 5, 6], name="Busy")
        task = Task(name="Homework", duration=timedelta(minutes=30), priority=5)

        result = self._scheduler([busy], [task]).solve(start_time=MONDAY_10AM)

        self.assertTrue(result.is_successful)
        self.assertEqual(len(result.scheduled_tasks), 1)
        self.assertEqual(result.scheduled_tasks[0].start_time.hour, 23)

    def test_task_avoids_the_single_blocked_weekday(self):
        """A task due Wednesday evening must dodge the Wednesday block, not sit inside it."""
        busy = _block(datetime(2020, 1, 1, 9, 0), datetime(2020, 1, 1, 20, 0), [2], name="Conference")
        task = Task(
            name="Report",
            duration=timedelta(minutes=60),
            priority=5,
            deadline=datetime(2026, 7, 8, 22, 0),
        )

        result = self._scheduler([busy], [task]).solve(start_time=datetime(2026, 7, 8, 8, 0))

        self.assertEqual(len(result.scheduled_tasks), 1)
        scheduled = result.scheduled_tasks[0]
        block_start = datetime(2026, 7, 8, 9, 0)
        block_end = datetime(2026, 7, 8, 20, 0)
        self.assertTrue(
            scheduled.end_time <= block_start or scheduled.start_time >= block_end,
            f"Task {scheduled.start_time}-{scheduled.end_time} overlaps the Wednesday block",
        )

    def test_occurrences_are_exported_once_per_matching_day(self):
        """Every Wednesday in the horizon shows up exactly once — no duplicates, no other weekday."""
        busy = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 0), [2], name="Lecture", id=3)

        result = self._scheduler([busy]).solve(start_time=MONDAY_10AM)

        exported = [b for b in result.scheduled_timeblocks if b.name == "Lecture"]
        days = [b.start_time.date() for b in exported]
        self.assertTrue(all(d.weekday() == 2 for d in days), days)
        self.assertEqual(len(days), len(set(days)), "each occurrence must be exported once")
        self.assertTrue(all(b.id == 3 for b in exported))

    def test_weekly_and_daily_blocks_coexist(self):
        daily = TimeBlock(start=datetime(2020, 1, 1, 12, 0), end=datetime(2020, 1, 1, 13, 0), daily=True, name="Lunch")
        weekly = _block(datetime(2020, 1, 1, 14, 0), datetime(2020, 1, 1, 15, 0), [2], name="Lecture")

        result = self._scheduler([daily, weekly]).solve(start_time=MONDAY_10AM)

        names = {b.name for b in result.scheduled_timeblocks}
        self.assertEqual(names, {"Lunch", "Lecture"})


if __name__ == "__main__":
    unittest.main()

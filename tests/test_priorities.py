from datetime import timedelta
import unittest

from src.data_structs import Task, TimeBlock
from tests.solver_test_utils import BaseSolverTest


class TestPriorities(BaseSolverTest):
    """Integration tests for the 2-Tier priority system in the scheduling solver."""

    # --- Tier dominance (High vs Low) ---

    def test_high_tier_beats_low_tier(self):
        """
        When only one task can fit, the High Tier task must be chosen
        over the Low Tier task — even if the Low Tier has a closer deadline.
        """
        # 60 min free slot: [0, 60], then blocked until horizon
        high = Task(name="university", duration=timedelta(minutes=60), priority=10, break_duration=timedelta(minutes=0))
        high.deadline_steps = 1440 * 7  # far deadline

        low = Task(name="personal", duration=timedelta(minutes=60), priority=9, break_duration=timedelta(minutes=0))
        low.deadline_steps = 100  # very close deadline

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([high, low], time_blocks=time_blocks)

        self.assertTrue(solver.value(high.presence_var), "High Tier task must be scheduled")
        self.assertFalse(solver.value(low.presence_var), "Low Tier task must be dropped")

    def test_high_tier_beats_multiple_low_tier(self):
        """
        A single High Tier task must beat ANY combination of Low Tier tasks.
        Here: 1 High Tier (60 min) vs 3 Low Tier (20 min each = 60 min total).
        """
        # 60 min free slot
        high = Task(name="uni_hw", duration=timedelta(minutes=60), priority=10, break_duration=timedelta(minutes=0))
        high.deadline_steps = None

        lows = [
            Task(name=f"personal_{i}", duration=timedelta(minutes=20), priority=9, break_duration=timedelta(minutes=0))
            for i in range(3)
        ]
        for t in lows:
            t.deadline_steps = 60  # urgent!

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([high] + lows, time_blocks=time_blocks)

        self.assertTrue(solver.value(high.presence_var), "High Tier task must be scheduled over all Low Tier")
        for t in lows:
            self.assertFalse(solver.value(t.presence_var), f"Low Tier task '{t.name}' must be dropped")

    # --- Within a tier (deadline dominance) ---

    def test_closer_deadline_preferred_in_conflict(self):
        """
        Within the same tier (Low), when only one task fits,
        the task with the closer deadline should be chosen.
        """
        task_close = Task(
            name="urgent", duration=timedelta(minutes=60), priority=2, break_duration=timedelta(minutes=0)
        )
        task_close.deadline_steps = 100

        task_far = Task(
            name="not_urgent", duration=timedelta(minutes=60), priority=9, break_duration=timedelta(minutes=0)
        )
        task_far.deadline_steps = 1440 * 7

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([task_close, task_far], time_blocks=time_blocks)

        self.assertTrue(solver.value(task_close.presence_var), "Closer deadline should win in 1-on-1")
        self.assertFalse(solver.value(task_far.presence_var))

    def test_priority_tiebreaker_same_deadline(self):
        """
        Same tier, same deadline: the task with the higher priority wins.
        """
        task_high_p = Task(
            name="high_prio", duration=timedelta(minutes=60), priority=8, break_duration=timedelta(minutes=0)
        )
        task_high_p.deadline_steps = 100

        task_low_p = Task(
            name="low_prio", duration=timedelta(minutes=60), priority=2, break_duration=timedelta(minutes=0)
        )
        task_low_p.deadline_steps = 100

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([task_high_p, task_low_p], time_blocks=time_blocks)

        self.assertTrue(solver.value(task_high_p.presence_var), "Higher priority should win as tiebreaker")
        self.assertFalse(solver.value(task_low_p.presence_var))

    def test_knapsack_phenomenon_within_tier(self):
        """
        Tests the documented 'Soft Priority' Knapsack behavior:
        Within the SAME tier, the solver maximizes total weight. If forced to choose
        between ONE urgent task and THREE non-urgent tasks (that together give a higher sum
        of weights), it will choose the three non-urgent tasks to maximize productivity.
        """
        # 60 min free slot
        urgent_task = Task(
            name="urgent_but_long", duration=timedelta(minutes=60), priority=2, break_duration=timedelta(minutes=0)
        )
        urgent_task.deadline_steps = 100  # very close deadline

        non_urgent_tasks = [
            Task(
                name=f"non_urgent_{i}", duration=timedelta(minutes=20), priority=9, break_duration=timedelta(minutes=0)
            )
            for i in range(3)
        ]
        for t in non_urgent_tasks:
            t.deadline_steps = 1440 * 7  # 1 week away

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([urgent_task] + non_urgent_tasks, time_blocks=time_blocks)

        self.assertFalse(
            solver.value(urgent_task.presence_var), "The single urgent task should be dropped due to knapsack behavior"
        )
        for t in non_urgent_tasks:
            self.assertTrue(solver.value(t.presence_var), f"The smaller non-urgent task '{t.name}' should be scheduled")

    # --- No conflict: all tasks fit ---

    def test_all_tasks_scheduled_when_room(self):
        """
        When there's enough time, all tasks should be scheduled
        regardless of priority or tier.
        """
        high = Task(name="uni", duration=timedelta(minutes=60), priority=10, break_duration=timedelta(minutes=0))
        high.deadline_steps = None

        low = Task(name="personal", duration=timedelta(minutes=60), priority=2, break_duration=timedelta(minutes=0))
        low.deadline_steps = None

        solver = self._solve([high, low])

        self.assertTrue(solver.value(high.presence_var))
        self.assertTrue(solver.value(low.presence_var))

    # --- Default priority ---

    def test_default_priority_zero(self):
        """Tasks without priority (default 0) should be schedulable."""
        task = Task(name="default", duration=timedelta(minutes=30), break_duration=timedelta(minutes=0))
        task.deadline_steps = None

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var))

    # --- Early Placement & Priority 0 ---

    def test_early_placement_sorts_by_priority(self):
        """
        If two tasks have the same deadline and tier, the one with
        higher priority should be scheduled earlier (closer to 0)
        because of the priority-based early placement bonus.
        """
        task_high_p = Task(
            name="high_p", duration=timedelta(minutes=60), priority=8, break_duration=timedelta(minutes=0)
        )
        task_high_p.deadline_steps = None

        task_low_p = Task(name="low_p", duration=timedelta(minutes=60), priority=2, break_duration=timedelta(minutes=0))
        task_low_p.deadline_steps = None

        solver = self._solve([task_high_p, task_low_p])

        self.assertTrue(solver.value(task_high_p.presence_var))
        self.assertTrue(solver.value(task_low_p.presence_var))

        start_high = solver.value(task_high_p.start_var)
        start_low = solver.value(task_low_p.start_var)

        self.assertLess(
            start_high, start_low, "Higher priority task should be scheduled earlier than lower priority task"
        )

    def test_priority_zero_floats(self):
        """
        A task with priority 0 has 0 multiplier for early placement,
        so it doesn't fight for the early slots. It should be placed
        after any task with priority > 0.
        """
        task_prio_1 = Task(
            name="prio_1", duration=timedelta(minutes=60), priority=1, break_duration=timedelta(minutes=0)
        )
        task_prio_1.deadline_steps = None

        task_prio_0 = Task(
            name="prio_0", duration=timedelta(minutes=60), priority=0, break_duration=timedelta(minutes=0)
        )
        task_prio_0.deadline_steps = None

        solver = self._solve([task_prio_1, task_prio_0])

        start_p1 = solver.value(task_prio_1.start_var)
        start_p0 = solver.value(task_prio_0.start_var)

        self.assertLess(start_p1, start_p0, "Priority > 0 should be scheduled before Priority 0")


if __name__ == "__main__":
    unittest.main()

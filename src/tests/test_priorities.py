import unittest

from data_structs import Task, TimeBlock
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
        high = Task(name="university", duration=60, priority=10, break_duration=0)
        high.deadline_min = 1440 * 7  # far deadline

        low = Task(name="personal", duration=60, priority=9, break_duration=0)
        low.deadline_min = 100  # very close deadline

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([high, low], time_blocks=time_blocks)

        self.assertTrue(solver.value(high.presence_var),
                        "High Tier task must be scheduled")
        self.assertFalse(solver.value(low.presence_var),
                         "Low Tier task must be dropped")

    def test_high_tier_beats_multiple_low_tier(self):
        """
        A single High Tier task must beat ANY combination of Low Tier tasks.
        Here: 1 High Tier (60 min) vs 3 Low Tier (20 min each = 60 min total).
        """
        # 60 min free slot
        high = Task(name="uni_hw", duration=60, priority=10, break_duration=0)
        high.deadline_min = None

        lows = [
            Task(name=f"personal_{i}", duration=20, priority=9, break_duration=0)
            for i in range(3)
        ]
        for t in lows:
            t.deadline_min = 60  # urgent!

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([high] + lows, time_blocks=time_blocks)

        self.assertTrue(solver.value(high.presence_var),
                        "High Tier task must be scheduled over all Low Tier")
        for t in lows:
            self.assertFalse(solver.value(t.presence_var),
                             f"Low Tier task '{t.name}' must be dropped")

    # --- Within a tier (deadline dominance) ---

    def test_closer_deadline_preferred_in_conflict(self):
        """
        Within the same tier (Low), when only one task fits,
        the task with the closer deadline should be chosen.
        """
        task_close = Task(name="urgent", duration=60, priority=2, break_duration=0)
        task_close.deadline_min = 100

        task_far = Task(name="not_urgent", duration=60, priority=9, break_duration=0)
        task_far.deadline_min = 1440 * 7

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([task_close, task_far], time_blocks=time_blocks)

        self.assertTrue(solver.value(task_close.presence_var),
                        "Closer deadline should win in 1-on-1")
        self.assertFalse(solver.value(task_far.presence_var))

    def test_priority_tiebreaker_same_deadline(self):
        """
        Same tier, same deadline: the task with the higher priority wins.
        """
        task_high_p = Task(name="high_prio", duration=60, priority=8, break_duration=0)
        task_high_p.deadline_min = 100

        task_low_p = Task(name="low_prio", duration=60, priority=2, break_duration=0)
        task_low_p.deadline_min = 100

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([task_high_p, task_low_p], time_blocks=time_blocks)

        self.assertTrue(solver.value(task_high_p.presence_var),
                        "Higher priority should win as tiebreaker")
        self.assertFalse(solver.value(task_low_p.presence_var))

    def test_knapsack_phenomenon_within_tier(self):
        """
        Tests the documented 'Soft Priority' Knapsack behavior:
        Within the SAME tier, the solver maximizes total weight. If forced to choose
        between ONE urgent task and THREE non-urgent tasks (that together give a higher sum
        of weights), it will choose the three non-urgent tasks to maximize productivity.
        """
        # 60 min free slot
        urgent_task = Task(name="urgent_but_long", duration=60, priority=2, break_duration=0)
        urgent_task.deadline_min = 100  # very close deadline
        
        non_urgent_tasks = [
            Task(name=f"non_urgent_{i}", duration=20, priority=9, break_duration=0)
            for i in range(3)
        ]
        for t in non_urgent_tasks:
            t.deadline_min = 1440 * 7  # 1 week away
            
        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]
        
        solver = self._solve([urgent_task] + non_urgent_tasks, time_blocks=time_blocks)
        
        self.assertFalse(solver.value(urgent_task.presence_var),
                         "The single urgent task should be dropped due to knapsack behavior")
        for t in non_urgent_tasks:
            self.assertTrue(solver.value(t.presence_var),
                            f"The smaller non-urgent task '{t.name}' should be scheduled")

    # --- No conflict: all tasks fit ---

    def test_all_tasks_scheduled_when_room(self):
        """
        When there's enough time, all tasks should be scheduled
        regardless of priority or tier.
        """
        high = Task(name="uni", duration=60, priority=10, break_duration=0)
        high.deadline_min = None

        low = Task(name="personal", duration=60, priority=2, break_duration=0)
        low.deadline_min = None

        solver = self._solve([high, low])

        self.assertTrue(solver.value(high.presence_var))
        self.assertTrue(solver.value(low.presence_var))

    # --- Default priority ---

    def test_default_priority_zero(self):
        """Tasks without priority (default 0) should be schedulable."""
        task = Task(name="default", duration=30, break_duration=0)
        task.deadline_min = None

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var))


if __name__ == '__main__':
    unittest.main()

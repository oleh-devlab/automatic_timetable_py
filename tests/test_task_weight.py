from datetime import timedelta
import unittest

from src.restrictions import calculate_task_weight
from src.data_structs import Task


class TestCalculateTaskWeight(unittest.TestCase):
    """Unit tests for the calculate_task_weight function (2-Tier logic with dynamic horizon)."""

    def setUp(self):
        self.horizon = 20000  # simulate ~14 days horizon

    # --- Tier separation ---

    def test_high_tier_always_dominates_low_tier(self):
        """
        The minimum High Tier weight must exceed the maximum possible
        Low Tier weight, guaranteeing absolute tier dominance.
        """
        # Minimum high tier: priority=10, no deadline (days_inverted=0)
        high = Task(name="uni", duration=timedelta(minutes=60), priority=10)
        high.deadline_min = None

        # Maximum low tier: priority=9, deadline in 0 days (days_inverted=3650)
        low = Task(name="personal", duration=timedelta(minutes=60), priority=9)
        low.deadline_min = 0  # deadline right now

        high_weight = calculate_task_weight(high, priority_threshold=10)
        low_weight = calculate_task_weight(low, priority_threshold=10)

        self.assertGreater(high_weight, low_weight, "Any High Tier task must outweigh any Low Tier task")

    def test_custom_priority_threshold(self):
        """Custom threshold separates tiers at a different level."""
        task = Task(name="t", duration=timedelta(minutes=60), priority=5)
        task.deadline_min = None

        # With threshold=5, task is High Tier
        weight_high = calculate_task_weight(task, priority_threshold=5)
        # With threshold=6, task is Low Tier
        weight_low = calculate_task_weight(task, priority_threshold=6)

        self.assertGreater(weight_high, weight_low)

    # --- Deadline influence within a tier ---

    def test_closer_deadline_has_higher_weight_same_tier(self):
        """Within the same tier, a closer deadline gives a higher weight."""
        task_close = Task(name="urgent", duration=timedelta(minutes=60), priority=3)
        task_close.deadline_min = 1440  # 1 day

        task_far = Task(name="distant", duration=timedelta(minutes=60), priority=3)
        task_far.deadline_min = 1440 * 7  # 7 days

        w_close = calculate_task_weight(task_close, priority_threshold=10)
        w_far = calculate_task_weight(task_far, priority_threshold=10)

        self.assertGreater(w_close, w_far)

    def test_closer_deadline_beats_higher_priority_same_tier(self):
        """
        Within the same tier (Low), a task with a closer deadline
        outweighs a task with a higher priority but distant deadline.
        This is the 1-on-1 "deadline dominates" behavior.
        """
        task_close = Task(name="urgent_low_prio", duration=timedelta(minutes=60), priority=1)
        task_close.deadline_min = 1440  # 1 day

        task_far = Task(name="not_urgent_high_prio", duration=timedelta(minutes=60), priority=9)
        task_far.deadline_min = 1440 * 30  # 30 days

        w_close = calculate_task_weight(task_close, priority_threshold=10)
        w_far = calculate_task_weight(task_far, priority_threshold=10)

        self.assertGreater(w_close, w_far)

    def test_no_deadline_has_lowest_weight_in_tier(self):
        """A task without a deadline gets the lowest weight in its tier."""
        task_with = Task(name="with_dl", duration=timedelta(minutes=60), priority=3)
        task_with.deadline_min = 1440 * 365  # even 1 year away

        task_without = Task(name="no_dl", duration=timedelta(minutes=60), priority=3)
        task_without.deadline_min = None

        w_with = calculate_task_weight(task_with, priority_threshold=10)
        w_without = calculate_task_weight(task_without, priority_threshold=10)

        self.assertGreater(w_with, w_without)

    # --- Priority as tiebreaker ---

    def test_priority_is_tiebreaker_for_same_deadline(self):
        """When deadlines are equal, higher priority wins."""
        task_high_prio = Task(name="high_p", duration=timedelta(minutes=60), priority=8)
        task_high_prio.deadline_min = 1440 * 3

        task_low_prio = Task(name="low_p", duration=timedelta(minutes=60), priority=2)
        task_low_prio.deadline_min = 1440 * 3

        w_high = calculate_task_weight(task_high_prio, priority_threshold=10)
        w_low = calculate_task_weight(task_low_prio, priority_threshold=10)

        self.assertGreater(w_high, w_low)

    # --- Edge cases ---

    def test_zero_priority(self):
        """Priority 0 (default) should work without errors."""
        task = Task(name="default", duration=timedelta(minutes=60), priority=0)
        task.deadline_min = None
        weight = calculate_task_weight(task, priority_threshold=10)
        # Should be low_tier_base + 0
        self.assertGreater(weight, 0)

    def test_deadline_at_zero(self):
        """Deadline at minute 0 (right now) should give maximum urgency within the tier."""
        task = Task(name="now", duration=timedelta(minutes=60), priority=5)
        task.deadline_min = 0
        weight_now = calculate_task_weight(task, priority_threshold=10)
        
        task_later = Task(name="later", duration=timedelta(minutes=60), priority=5)
        task_later.deadline_min = 1440
        weight_later = calculate_task_weight(task_later, priority_threshold=10)
        
        self.assertGreater(weight_now, weight_later)

    def test_very_distant_deadline(self):
        """A deadline far in the future (> 3650 days) should clamp days_inverted to 0."""
        task1 = Task(name="far1", duration=timedelta(minutes=60), priority=5)
        task1.deadline_min = 1440 * 4000  # ~11 years
        weight1 = calculate_task_weight(task1, priority_threshold=10)
        
        task2 = Task(name="far2", duration=timedelta(minutes=60), priority=5)
        task2.deadline_min = 1440 * 5000  # ~13 years
        weight2 = calculate_task_weight(task2, priority_threshold=10)
        
        # Both should be clamped, so their weights should be exactly equal
        self.assertEqual(weight1, weight2)


if __name__ == "__main__":
    unittest.main()

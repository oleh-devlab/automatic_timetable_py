from datetime import timedelta
import unittest

from src.data_structs import Task, TimeBlock
from tests.solver_test_utils import BaseSolverTest


class TestDeadlines(BaseSolverTest):
    """Tests for deadline constraints in the scheduling solver."""

    def test_task_ends_before_deadline(self):
        """
        A task with a generous deadline should be scheduled and
        must finish before (or at) the deadline.
        """
        task = Task(name="with_deadline", duration=timedelta(minutes=60), break_duration=timedelta(minutes=0))
        task.deadline_steps = 500  # plenty of room

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var), "Task should be scheduled when deadline is generous")
        self.assertLessEqual(solver.value(task.end_var), 500)

    def test_impossible_deadline_drops_task(self):
        """
        All-or-Nothing: if a task cannot fully fit before the deadline,
        it must be entirely skipped.
        """
        # Block [0, 100], deadline at 120 → only 20 min free, but task needs 60
        task = Task(name="tight", duration=timedelta(minutes=60), break_duration=timedelta(minutes=0))
        task.deadline_steps = 120

        time_blocks = [TimeBlock(start=0, end=100, daily=False)]

        solver = self._solve([task], time_blocks=time_blocks)

        self.assertFalse(solver.value(task.presence_var), "Task should be dropped — not enough time before deadline")

    def test_deadline_exact_fit(self):
        """
        A task that fits *exactly* into the gap before the deadline
        should be scheduled.
        """
        # Free time: [0, 60], deadline at 60
        task = Task(name="exact_deadline", duration=timedelta(minutes=60), break_duration=timedelta(minutes=0))
        task.deadline_steps = 60

        time_blocks = [TimeBlock(start=60, end=30000, daily=False)]

        solver = self._solve([task], time_blocks=time_blocks)

        self.assertTrue(solver.value(task.presence_var), "Task fits exactly before deadline")
        self.assertEqual(solver.value(task.start_var), 0)
        self.assertEqual(solver.value(task.end_var), 60)

    def test_chunked_task_respects_deadline(self):
        """
        A chunked task with a deadline: all chunks must finish
        before the deadline.
        """
        task = Task(
            name="chunked_deadline", duration=timedelta(minutes=100), min_chunk_duration=timedelta(minutes=20), max_chunk_duration=timedelta(minutes=40), break_duration=timedelta(minutes=5)
        )
        task.deadline_steps = 500

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var))
        # end_var points to the last chunk's end
        self.assertLessEqual(solver.value(task.end_var), 500)

    def test_chunked_task_impossible_deadline(self):
        """
        A chunked task that cannot fit all its chunks (with breaks)
        before the deadline should be entirely dropped.

        100 min task, chunks 20-40 min, breaks 5 min.
        Minimum time needed: e.g. 3 chunks (40+40+20) + 2 breaks (5+5) = 110 min.
        Deadline at 30 min makes it impossible.
        """
        task = Task(name="chunked_no_fit", duration=timedelta(minutes=100), min_chunk_duration=timedelta(minutes=20), max_chunk_duration=timedelta(minutes=40), break_duration=timedelta(minutes=5))
        task.deadline_steps = 30

        solver = self._solve([task])

        self.assertFalse(solver.value(task.presence_var), "Chunked task should be dropped when deadline is too tight")

    def test_deadline_does_not_affect_other_tasks(self):
        """
        A task with an impossible deadline gets dropped, but other
        tasks without deadlines should still be scheduled.
        """
        task_deadline = Task(name="doomed", duration=timedelta(minutes=60), break_duration=timedelta(minutes=0))
        task_deadline.deadline_steps = 10  # impossible

        task_free = Task(name="free", duration=timedelta(minutes=60), break_duration=timedelta(minutes=0))
        task_free.deadline_steps = None

        solver = self._solve([task_deadline, task_free])

        self.assertFalse(solver.value(task_deadline.presence_var), "Task with impossible deadline should be dropped")
        self.assertTrue(solver.value(task_free.presence_var), "Task without deadline should still be scheduled")

    def test_deadline_pushes_task_earlier(self):
        """
        A task with a deadline should be scheduled *before* the deadline,
        even when there's free time after it. Verify that the solver
        doesn't place it after the deadline.
        """
        task = Task(name="urgent", duration=timedelta(minutes=30), break_duration=timedelta(minutes=0))
        task.deadline_steps = 100

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var))
        self.assertLessEqual(solver.value(task.end_var), 100)

    def test_two_tasks_with_different_deadlines(self):
        """
        Two tasks with different deadlines: both should be scheduled
        and each must respect its own deadline.
        """
        task_a = Task(name="early_deadline", duration=timedelta(minutes=30), break_duration=timedelta(minutes=5))
        task_a.deadline_steps = 100

        task_b = Task(name="late_deadline", duration=timedelta(minutes=30), break_duration=timedelta(minutes=5))
        task_b.deadline_steps = 500

        solver = self._solve([task_a, task_b])

        self.assertTrue(solver.value(task_a.presence_var))
        self.assertTrue(solver.value(task_b.presence_var))
        self.assertLessEqual(solver.value(task_a.end_var), 100)
        self.assertLessEqual(solver.value(task_b.end_var), 500)

    def test_deadline_with_blocked_time_before(self):
        """
        Deadline at 200, but [0, 100] is blocked.
        Task of 90 min needs to fit in [100, 200]. It should succeed
        since the gap is exactly 100 min.
        """
        task = Task(name="after_block", duration=timedelta(minutes=90), break_duration=timedelta(minutes=0))
        task.deadline_steps = 200

        time_blocks = [TimeBlock(start=0, end=100, daily=False)]

        solver = self._solve([task], time_blocks=time_blocks)

        self.assertTrue(solver.value(task.presence_var))
        self.assertGreaterEqual(solver.value(task.start_var), 100)
        self.assertLessEqual(solver.value(task.end_var), 200)

    def test_deadline_conflict_prefers_more_tasks(self):
        """
        Two tasks compete for the same slot before a deadline.
        Only one can fit. The solver should schedule exactly one
        (maximizing the count of scheduled tasks).
        """
        task_a = Task(name="competitor_a", duration=timedelta(minutes=80), break_duration=timedelta(minutes=0))
        task_a.deadline_steps = 100

        task_b = Task(name="competitor_b", duration=timedelta(minutes=80), break_duration=timedelta(minutes=0))
        task_b.deadline_steps = 100

        time_blocks = [TimeBlock(start=100, end=30000, daily=False)]

        solver = self._solve([task_a, task_b], time_blocks=time_blocks)

        a_present = solver.value(task_a.presence_var)
        b_present = solver.value(task_b.presence_var)

        # Exactly one should be scheduled
        self.assertEqual(a_present + b_present, 1, "Only one of two competing tasks should fit before the deadline")


if __name__ == "__main__":
    unittest.main()

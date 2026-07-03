from datetime import timedelta, datetime
import unittest

from src.routine_expansion import expand_routines
from src.data_structs import Task, Routine
from tests.solver_test_utils import BaseSolverTest


class TestDependencies(BaseSolverTest):
    """Tests for task dependencies (depends_on)."""

    def test_simple_dependency(self):
        """Task B depends on Task A. B should start after A ends."""
        task_a = Task(name="A", id=1, duration=timedelta(minutes=60))
        task_b = Task(name="B", id=2, duration=timedelta(minutes=30), depends_on=[1])

        solver = self._solve([task_a, task_b])

        self.assertTrue(solver.value(task_a.presence_var), "Task A should be scheduled")
        self.assertTrue(solver.value(task_b.presence_var), "Task B should be scheduled")

        a_end = solver.value(task_a.end_var)
        b_start = solver.value(task_b.start_var)

        self.assertGreaterEqual(b_start, a_end, "Task B must start after Task A ends")

    def test_dependency_with_chunks(self):
        """Task B depends on chunked Task A. B starts after the LAST chunk of A."""
        task_a = Task(
            name="A", 
            id=1, 
            duration=timedelta(minutes=120), 
            min_chunk_duration=timedelta(minutes=30), 
            max_chunk_duration=timedelta(minutes=60),
            break_duration=timedelta(minutes=10)
        )
        task_b = Task(name="B", id=2, duration=timedelta(minutes=30), depends_on=[1])

        solver = self._solve([task_a, task_b])

        self.assertTrue(solver.value(task_a.presence_var), "Task A should be scheduled")
        self.assertTrue(solver.value(task_b.presence_var), "Task B should be scheduled")

        a_end = solver.value(task_a.end_var)
        b_start = solver.value(task_b.start_var)

        self.assertGreaterEqual(b_start, a_end, "Task B must start after the final chunk of Task A ends")
        
        # Verify A actually got chunked
        present_chunks, _ = self._get_present_and_absent_chunks(solver, task_a)
        self.assertGreater(len(present_chunks), 1, "Task A should be chunked")

    def test_implication_dependency(self):
        """If Task A is impossible to schedule, Task B (which depends on A) must also not be scheduled."""
        # A has an impossible deadline
        task_a = Task(name="A", id=1, duration=timedelta(minutes=60))
        # We manually set deadline_steps after initialization like other tests do
        task_a.deadline_steps = 10 
        
        task_b = Task(name="B", id=2, duration=timedelta(minutes=30), depends_on=[1])

        solver = self._solve([task_a, task_b])

        self.assertFalse(solver.value(task_a.presence_var), "Task A should NOT be scheduled")
        self.assertFalse(solver.value(task_b.presence_var), "Task B should NOT be scheduled because it depends on A")

    def test_multiple_dependencies(self):
        """Task C depends on both A and B. C must start after BOTH A and B end."""
        task_a = Task(name="A", id=1, duration=timedelta(minutes=30))
        task_b = Task(name="B", id=2, duration=timedelta(minutes=30))
        task_c = Task(name="C", id=3, duration=timedelta(minutes=30), depends_on=[1, 2])

        solver = self._solve([task_a, task_b, task_c])

        self.assertTrue(solver.value(task_c.presence_var), "Task C should be scheduled")
        
        a_end = solver.value(task_a.end_var)
        b_end = solver.value(task_b.end_var)
        c_start = solver.value(task_c.start_var)

        self.assertGreaterEqual(c_start, a_end, "Task C must start after A ends")
        self.assertGreaterEqual(c_start, b_end, "Task C must start after B ends")

    def test_routine_depends_on_routine(self):
        """Routine B depends on Routine A. After expansion, B should start after A on the same day."""        
        routine_a = Routine(name="Routine A", id=10, type="flexible", repeat="daily", duration=timedelta(minutes=20))
        routine_b = Routine(name="Routine B", id=11, type="flexible", repeat="daily", duration=timedelta(minutes=30), depends_on=[10])
        
        routine_a.duration_steps = 20
        routine_a.break_duration_steps = 0
        routine_b.duration_steps = 30
        routine_b.break_duration_steps = 0
        
        now = datetime(2026, 7, 6, 10, 0)
        extra_tasks, _, _ = expand_routines([routine_a, routine_b], now, horizon_minutes=1440, step_minutes=1)
        
        # extra_tasks should contain tasks for A and B.
        solver = self._solve(extra_tasks)
        
        task_a = next(t for t in extra_tasks if t.name.startswith("Routine A"))
        task_b = next(t for t in extra_tasks if t.name.startswith("Routine B"))
        
        self.assertTrue(solver.value(task_a.presence_var))
        self.assertTrue(solver.value(task_b.presence_var))
        
        a_end = solver.value(task_a.end_var)
        b_start = solver.value(task_b.start_var)
        
        self.assertGreaterEqual(b_start, a_end, "Routine B must start after Routine A on the same day")

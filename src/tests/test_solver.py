import unittest
from ortools.sat.python import cp_model

from restrictions import create_model
from data_structs import Task, TimeBlock
from tests.solver_test_utils import BaseSolverTest

class TestSolver(BaseSolverTest):
    """Tests for the scheduling solver, verifying solutions via create_model + CpSolver."""

    def test_chunk_sizes_and_presence(self):
        """
        A single chunked task with no obstacles.

        Checks:
          1. The sum of all present chunk sizes equals the total task duration.
          2. No chunk exceeds max_chunk_duration.
          3. No chunk (except possibly the last present one) is smaller than min_chunk_duration.
          4. Unused chunks have size 0 and presence False.
        """
        task = Task(
            name="chunked_task",
            duration=120,
            min_chunk_duration=25,
            max_chunk_duration=50,
            break_duration=5
        )

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var),
                        "The task should be scheduled since there are no conflicts")

        present, absent = self._get_present_and_absent_chunks(solver, task)
        self.assertGreater(len(present), 0)

        # 1. Sum of present chunk sizes == total task duration
        total_size = sum(solver.value(c['size_var']) for c in present)
        self.assertEqual(total_size, task.duration)

        # 2. No chunk exceeds max_chunk_duration
        for c in present:
            self.assertLessEqual(solver.value(c['size_var']), task.max_chunk_duration)

        # 3. No non-last chunk is smaller than min_chunk_duration
        for c in present[:-1]:
            self.assertGreaterEqual(solver.value(c['size_var']), task.min_chunk_duration)

        # 4. Unused chunks have size 0 and presence False
        for c in absent:
            self.assertFalse(solver.value(c['presence_var']))
            self.assertEqual(solver.value(c['size_var']), 0)

    def test_intra_task_breaks(self):
        """
        Intra-task Breaks
        Situation: A task is split into multiple chunks.
        Checks:
          1. The start time of the next chunk (start_var) must be greater than or equal to
             the end time of the previous chunk (end_var) plus task.break_duration.
        """
        task = Task(
            name="task_with_breaks",
            duration=100,
            min_chunk_duration=20,
            max_chunk_duration=30,
            break_duration=15
        )

        solver = self._solve([task])

        self.assertTrue(solver.value(task.presence_var),
                        "The task should be scheduled")

        present, _ = self._get_present_and_absent_chunks(solver, task)
        self.assertGreater(len(present), 1,
                           "Task should be split into multiple chunks for this test")

        for i in range(len(present) - 1):
            curr_chunk = present[i]
            next_chunk = present[i + 1]
            
            curr_end = solver.value(curr_chunk['end_var'])
            next_start = solver.value(next_chunk['start_var'])
            
            self.assertGreaterEqual(
                next_start, 
                curr_end + task.break_duration,
                f"Chunk {i+1} starts at {next_start}, but chunk {i} ended at {curr_end} "
                f"with a break duration of {task.break_duration}."
            )

    def test_inter_task_breaks(self):
        """
        Inter-task Breaks
        Situation: Two different tasks that fit into one day.
        Checks: The time between the end of Task A and the start of Task B 
        must be >= the break_duration of the preceding task. They cannot be scheduled back-to-back.
        """
        # We use non-chunked tasks to ensure one fully completes before/after the other, 
        # making it easy to test the gap between them.
        task_a = Task(name="A", duration=60, break_duration=15)
        task_b = Task(name="B", duration=60, break_duration=20)
        
        solver = self._solve([task_a, task_b])
        
        self.assertTrue(solver.value(task_a.presence_var), "Task A should be scheduled")
        self.assertTrue(solver.value(task_b.presence_var), "Task B should be scheduled")
        
        a_start = solver.value(task_a.start_var)
        a_end = solver.value(task_a.end_var)
        
        b_start = solver.value(task_b.start_var)
        b_end = solver.value(task_b.end_var)
        
        if a_start < b_start:
            # A comes before B
            self.assertGreaterEqual(
                b_start, a_end + task_a.break_duration,
                f"Task B (starts {b_start}) should respect Task A's break (ends {a_end}, break {task_a.break_duration})"
            )
        else:
            # B comes before A
            self.assertGreaterEqual(
                a_start, b_end + task_b.break_duration,
                f"Task A (starts {a_start}) should respect Task B's break (ends {b_end}, break {task_b.break_duration})"
            )

    def test_overlay_trick_break_on_blocked_time(self):
        """
        The "Overlay" Trick
        Situation: A hard blocked interval (e.g., from 50 to the end of the horizon) 
        and a task with duration 50 and break 15.
        Checks:
          1. The model successfully finds a solution.
          2. The task itself (strict interval) fits exactly in [0, 50].
          3. The algorithm allows the extended interval (break) to overlap with 
             the blocked time without penalizing the task scheduling.
        """
        task = Task(name="tight_task", duration=50, break_duration=15)
        # Block from 50 up to 30000 (which is > max possible horizon 20160)
        time_blocks = [TimeBlock(start=50, end=30000, daily=False)]
        
        solver = self._solve([task], time_blocks=time_blocks)
        
        self.assertTrue(
            solver.value(task.presence_var),
            "The task should be scheduled even if its break overlaps with the blocked interval"
        )
        
        self.assertEqual(
            solver.value(task.end_var), 50,
            "Task must end at 50, touching the blocked interval"
        )

    def test_the_squeeze_dropping(self):
        """
        The Squeeze / Dropping
        Situation: Available free time is less than needed for a task.
        Checks:
          1. The solver does not crash (returns OPTIMAL/FEASIBLE).
          2. The impossible task gets presence_var == False (dropped gracefully).
          3. A smaller task that fits gets scheduled (maximizing scheduled tasks).
        """
        # Block everything from minute 10 onwards
        time_blocks = [TimeBlock(start=10, end=30000, daily=False)]
        
        task_small = Task(name="fits", duration=10, break_duration=0)
        task_large = Task(name="no_fit", duration=20, break_duration=0)
        
        solver = self._solve([task_small, task_large], time_blocks=time_blocks)
        
        self.assertTrue(
            solver.value(task_small.presence_var), 
            "Small task should fit in 0..10"
        )
        self.assertFalse(
            solver.value(task_large.presence_var), 
            "Large task should be dropped gracefully without causing INFEASIBLE"
        )

    def test_edge_of_tomorrow(self):
        """
        Edge of Tomorrow
        Situation: A task is scheduled exactly at the end of the planning horizon.
        Checks:
          1. The model finds a solution.
          2. The task ends exactly at `horizon`.
          3. The extended interval (break) safely goes beyond `horizon` 
             (since its domain is up to horizon * 2) without crashing the solver.
        """
        # 1. Figure out what the horizon will be.
        # For a single task of 100 min: max(100*3 + 1440, 14*1440) = 20160
        expected_horizon = 20160
        
        task = Task(name="edge_task", duration=100, break_duration=30)
        
        # Force it to the very end. We block from 0 up to expected_horizon - 100.
        # So the only free time is [20060, 20160] (length 100).
        time_blocks = [TimeBlock(start=0, end=expected_horizon - 100, daily=False)]
        
        solver = self._solve([task], time_blocks=time_blocks)
        
        self.assertTrue(
            solver.value(task.presence_var), 
            "Task should be scheduled at the edge of the horizon"
        )
        self.assertEqual(
            solver.value(task.end_var), expected_horizon, 
            "Task should end exactly at the horizon boundary"
        )

    def test_impossible_math(self):
        """
        The Impossible Math
        Situation: Task parameters physically contradict each other 
        (e.g., min_chunk > max_chunk).
        Checks:
          1. The Task class constructor raises a ValueError.
        """
        with self.assertRaises(ValueError):
            Task(name="impossible", duration=100, min_chunk_duration=60, max_chunk_duration=40, break_duration=5)

    def test_chunked_task_schedules_when_plenty_of_free_time(self):
        """
        Regression test: a task that requires chunking must always be
        scheduled when there is more than enough free time available.
        The key point: unused chunks must not "steal" any minutes
        (their size must be 0).
        """
        task = Task(
            name="plenty",
            duration=100,
            min_chunk_duration=20,
            max_chunk_duration=40,
            break_duration=5,
        )

        # No blocking time intervals.
        solver = self._solve([task], time_blocks=[])

        self.assertTrue(
            solver.value(task.presence_var),
            "Task should be scheduled when there is plenty of free time",
        )

        used_chunks, unused_chunks = self._get_present_and_absent_chunks(solver, task)

        # The total duration of scheduled chunks must equal the task duration.
        self.assertEqual(
            sum(solver.value(c["size_var"]) for c in used_chunks),
            task.duration,
        )

        # Unused chunks must not "steal" any minutes.
        for c in unused_chunks:
            self.assertEqual(solver.value(c["size_var"]), 0)

    def test_needs_chunking_strict_inequality(self):
        """
        Verify that when task.duration == task.min_chunk_duration,
        needs_chunking is False and the task is NOT split.
        """
        task = Task(name="no_split", duration=30, min_chunk_duration=30, max_chunk_duration=30)
        solver = self._solve([task])
        self.assertTrue(solver.value(task.presence_var))
        # if it wasn't chunked, task.chunks will be empty
        self.assertEqual(len(task.chunks), 0)

    def test_duration_zero_raises_error(self):
        """Task duration <= 0 should raise ValueError upon creation."""
        with self.assertRaises(ValueError):
            Task(name="zero_task", duration=0)
        with self.assertRaises(ValueError):
            Task(name="neg_task", duration=-10)

    def test_empty_tasks_and_blocks(self):
        """0 tasks, 0 blocks -> model trivially solves without crashing."""
        solver = self._solve([], [])
        # The invariants are automatically checked inside _solve and should pass.

    def test_exact_fit_no_margin(self):
        """
        A task should fit perfectly in an exact slot without any margin.
        This is an extreme edge case for no-overlap.
        """
        task = Task(name="exact", duration=30, break_duration=0)
        
        # We block everything except [100, 130].
        time_blocks = [
            TimeBlock(start=0, end=100, daily=False),
            TimeBlock(start=130, end=30000, daily=False)
        ]
        
        solver = self._solve([task], time_blocks=time_blocks)
        
        self.assertTrue(solver.value(task.presence_var), "Task should schedule into the exact gap")
        self.assertEqual(solver.value(task.start_var), 100, "Must start exactly at 100")
        self.assertEqual(solver.value(task.end_var), 130, "Must end exactly at 130")

    def test_inter_task_breaks_mixed(self):
        """
        Inter-task Breaks (Mixed Chunked and Non-Chunked)
        Situation: Task A is chunked, Task B is not.
        Checks: The transition between any chunk of Task A and Task B
        respects the appropriate break_duration (the extended interval).
        """
        task_a = Task(name="chunked", duration=90, min_chunk_duration=30, max_chunk_duration=30, break_duration=15)
        task_b = Task(name="solid", duration=60, break_duration=20)
        
        solver = self._solve([task_a, task_b])
        
        self.assertTrue(solver.value(task_a.presence_var), "Task A should be scheduled")
        self.assertTrue(solver.value(task_b.presence_var), "Task B should be scheduled")
        
        b_start = solver.value(task_b.start_var)
        b_end = solver.value(task_b.end_var)
        
        present_a, _ = self._get_present_and_absent_chunks(solver, task_a)
        
        for chunk in present_a:
            c_start = solver.value(chunk['start_var'])
            c_end = solver.value(chunk['end_var'])
            
            # They cannot overlap, and must respect breaks
            if c_start >= b_start:
                # B comes before this chunk
                self.assertGreaterEqual(
                    c_start, b_end + task_b.break_duration,
                    f"Chunk of Task A (starts {c_start}) must respect Task B's break (ends {b_end}, break {task_b.break_duration})"
                )
            else:
                # This chunk comes before B
                self.assertGreaterEqual(
                    b_start, c_end + task_a.break_duration,
                    f"Task B (starts {b_start}) must respect Task A chunk's break (ends {c_end}, break {task_a.break_duration})"
                )

    def test_dropping_chunked_tasks(self):
        """
        Dropping Chunked Tasks
        Situation: A large chunked task cannot fit in the available time.
        Checks:
          1. The task is dropped (presence_var == False).
          2. ALL of its chunks are also successfully zeroed out 
             (presence_var == False, size_var == 0) to prevent phantom intervals.
        """
        from data_structs import TimeBlock
        
        # Block almost everything, leave only 10 minutes free
        time_blocks = [TimeBlock(start=10, end=30000, daily=False)]
        
        # Task requires 60 min, chunked into pieces of 20
        task = Task(name="big_chunked", duration=60, min_chunk_duration=20, max_chunk_duration=20, break_duration=5)
        
        solver = self._solve([task], time_blocks=time_blocks)
        
        self.assertFalse(solver.value(task.presence_var), "Task should be dropped")
        
        _, absent = self._get_present_and_absent_chunks(solver, task)
        
        self.assertEqual(len(absent), len(task.chunks), "All chunks must be absent")
        
        for c in absent:
            self.assertFalse(solver.value(c['presence_var']))
            self.assertEqual(solver.value(c['size_var']), 0)

if __name__ == '__main__':
    unittest.main()

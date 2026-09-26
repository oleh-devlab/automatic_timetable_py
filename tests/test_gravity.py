from datetime import timedelta
from itertools import pairwise
import unittest

from src.data_structs import Task, TimeBlock
from tests.solver_test_utils import BaseSolverTest


def _chunk_bounds(solver, task):
    """Present chunk (start, end) pairs in calendar order, in steps."""
    if not task.chunks:
        return [(solver.value(task.start_var), solver.value(task.end_var))]
    return sorted(
        (solver.value(chunk["start_var"]), solver.value(chunk["end_var"]))
        for chunk in task.chunks
        if solver.value(chunk["presence_var"])
    )


class TestGravity(BaseSolverTest):
    """
    Stage 2 decides *where* tasks sit. A task is one thing however many pieces the
    calendar cuts it into: every piece is pulled towards the present, no cheaper task
    gets to sit between them, and the split itself neither raises nor lowers the task's
    claim on the early hours.
    """

    def test_lower_priority_task_does_not_split_a_higher_priority_one(self):
        """
        A priority 2 task must not wedge itself between the chunks of a priority 5 one.
        Both fit with room to spare, so nothing forces the split.
        """
        high = Task(
            name="high",
            duration=timedelta(hours=4),
            priority=5,
            min_chunk_duration=timedelta(hours=1),
            max_chunk_duration=timedelta(hours=2),
            break_duration=timedelta(minutes=0),
        )
        high.deadline_steps = None

        low = Task(name="low", duration=timedelta(hours=2), priority=2, break_duration=timedelta(minutes=0))
        low.deadline_steps = None

        solver = self._solve([high, low])

        high_chunks = _chunk_bounds(solver, high)
        low_start = solver.value(low.start_var)

        for start, end in high_chunks:
            self.assertFalse(
                start <= low_start < end,
                "Lower priority task was placed inside the higher priority task",
            )
        self.assertGreaterEqual(
            low_start,
            high_chunks[-1][1],
            "Lower priority task must not start before the higher priority one is finished",
        )

    def test_chunks_stay_contiguous_when_nothing_forces_a_split(self):
        """
        With an empty calendar every chunk should butt up against the previous one:
        each one is pulled left on its own, not just the first.
        """
        task = Task(
            name="long",
            duration=timedelta(hours=6),
            priority=3,
            min_chunk_duration=timedelta(hours=1),
            max_chunk_duration=timedelta(hours=2),
            break_duration=timedelta(minutes=0),
        )
        task.deadline_steps = None

        solver = self._solve([task])

        chunks = _chunk_bounds(solver, task)
        self.assertGreater(len(chunks), 1, "Task should have been split into several chunks")
        for (_, prev_end), (start, _) in pairwise(chunks):
            self.assertEqual(start, prev_end, "Chunks should be contiguous when the calendar is free")

    def test_middle_chunks_hold_their_ground_too(self):
        """
        Not just the head and the tail: with several cheaper tasks competing, every chunk
        of the expensive task has to hold its slot. Weighing the pull by mass is what
        makes a chunk expensive to displace; the gap penalty alone is 100x too weak.
        """
        task = Task(
            name="chunked",
            duration=timedelta(hours=6),
            priority=6,
            min_chunk_duration=timedelta(hours=1),
            max_chunk_duration=timedelta(hours=2),
            break_duration=timedelta(minutes=0),
        )
        task.deadline_steps = None

        fillers = []
        for i in range(2):
            filler = Task(
                name=f"filler_{i}", duration=timedelta(hours=1), priority=2, break_duration=timedelta(minutes=0)
            )
            filler.deadline_steps = None
            fillers.append(filler)

        solver = self._solve([task, *fillers])

        chunks = _chunk_bounds(solver, task)
        self.assertGreater(len(chunks), 2, "Task should have been split into more than two chunks")
        self.assertEqual(
            chunks[-1][1] - chunks[0][0],
            task.duration_steps,
            "Cheaper tasks must not wedge themselves between the chunks of an expensive one",
        )

    def test_split_forced_by_a_blocked_window_is_still_allowed(self):
        """
        Gravity discourages gaps, it does not forbid them. Only 2h of free time sits in
        front of a 4h task, so it has to straddle the blocked window — the pull must not
        turn into something that refuses the split or pushes the whole task past the block.
        """
        task = Task(
            name="straddles",
            duration=timedelta(hours=4),
            priority=5,
            min_chunk_duration=timedelta(hours=1),
            max_chunk_duration=timedelta(hours=2),
            break_duration=timedelta(minutes=0),
        )
        task.deadline_steps = None

        # Blocked 02:00 -> 03:00, once, so only 2h of free time sits before the gap.
        blocked = TimeBlock(start=120, end=180, daily=False, name="blocked")

        solver = self._solve([task], time_blocks=[blocked])

        self.assertTrue(solver.value(task.presence_var), "Task should still be scheduled")
        chunks = _chunk_bounds(solver, task)
        self.assertEqual(chunks[0][0], 0, "The task should still start as early as it can")
        self.assertGreater(
            chunks[-1][1] - chunks[0][0],
            task.duration_steps,
            "The task has to straddle the blocked window, so its span must exceed its duration",
        )

    def test_a_chunked_task_does_not_jump_ahead_of_a_higher_priority_one(self):
        """
        How a task is cut up is a calendar detail, not a claim on the schedule. Two tasks
        of the same length are separated by priority alone, whether or not either of them
        is chunked — so the priority 3 task waits for the priority 4 one even though it
        arrives in eight pieces.
        """
        chunked = Task(
            name="chunked",
            duration=timedelta(hours=4),
            priority=3,
            min_chunk_duration=timedelta(minutes=30),
            max_chunk_duration=timedelta(minutes=30),
            break_duration=timedelta(minutes=0),
        )
        chunked.deadline_steps = None

        solid = Task(name="solid", duration=timedelta(hours=4), priority=4, break_duration=timedelta(minutes=0))
        solid.deadline_steps = None

        solver = self._solve([chunked, solid])

        self.assertLess(
            solver.value(solid.start_var),
            _chunk_bounds(solver, chunked)[0][0],
            "Being splittable is not extra importance: the higher priority task goes first",
        )

    def test_a_chunked_task_does_not_fall_behind_a_lower_priority_one(self):
        """
        The mirror of the case above, and the one that catches a task being *demoted* for
        how finely it can be cut. `min_chunk_duration` says what a workable sitting is; it
        must not decide who gets the morning, so the priority 4 task still goes first.
        """
        divisible = Task(
            name="divisible",
            duration=timedelta(hours=4),
            priority=4,
            min_chunk_duration=timedelta(minutes=30),
            max_chunk_duration=timedelta(hours=2),
            break_duration=timedelta(minutes=0),
        )
        divisible.deadline_steps = None

        solid = Task(name="solid", duration=timedelta(hours=4), priority=3, break_duration=timedelta(minutes=0))
        solid.deadline_steps = None

        solver = self._solve([divisible, solid])

        self.assertLess(
            _chunk_bounds(solver, divisible)[0][0],
            solver.value(solid.start_var),
            "A chunked task keeps its priority; how finely it could be cut is not a demotion",
        )


class TestGravityCoarseSteps(TestGravity):
    """Same assertions at a coarser granularity."""

    step_minutes = 5


if __name__ == "__main__":
    unittest.main()

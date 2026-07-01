import unittest
from datetime import datetime

from ortools.sat.python import cp_model

from data_structs import Task, TimeBlock, Routine
from restrictions import create_model, calculate_horizon
from routine_expansion import expand_routines
from tests.solver_test_utils import BaseSolverTest


class TestRoutinesSolver(BaseSolverTest):
    """Integration tests: routines expanded and solved through the CP-SAT solver."""

    def _expand_and_solve(self, routines, user_tasks=None, time_blocks=None,
                          now=None, max_horizon_days=14):
        """
        Helper: expands routines, merges with user_tasks/time_blocks,
        builds the model, and solves it. Returns (solver, all_tasks, routine_info).
        """
        if user_tasks is None:
            user_tasks = []
        if time_blocks is None:
            time_blocks = []
        if now is None:
            now = datetime(2026, 7, 6, 10, 0)

        # Compute deadlines for user tasks
        for task in user_tasks:
            if task.deadline is not None:
                dt = datetime.strptime(task.deadline, "%d.%m.%Y %H:%M")
                task.deadline_min = int((dt - now).total_seconds() / 60)
            else:
                task.deadline_min = None

        horizon = calculate_horizon(user_tasks, max_horizon_days)
        extra_tasks, extra_blocks, routine_info = expand_routines(routines, now, horizon)
        user_tasks.extend(extra_tasks)
        time_blocks.extend(extra_blocks)

        model = create_model(user_tasks, time_blocks, horizon=horizon)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 1
        status = solver.solve(model)

        self.assertIn(status, (cp_model.OPTIMAL, cp_model.FEASIBLE),
                      "Solver failed to find a feasible solution")
        self._assert_invariants(solver, user_tasks, time_blocks)

        return solver, user_tasks, routine_info

    def test_flexible_routine_does_not_conflict_with_time_blocks(self):
        """
        A flexible routine must not overlap with existing time blocks.
        We leave only a narrow window and verify the routine fits there.
        """
        routine = Routine(
            name="Study", type="flexible", repeat="daily",
            duration=30, priority=5, deadline_time="23:59"
        )
        # Block everything except [100, 200]
        time_blocks = [
            TimeBlock(start=0, end=100, daily=False),
            TimeBlock(start=200, end=30000, daily=False)
        ]
        now = datetime(2026, 7, 6, 10, 0)

        solver, all_tasks, _ = self._expand_and_solve(
            [routine], time_blocks=time_blocks, now=now
        )

        routine_tasks = [t for t in all_tasks if getattr(t, 'is_routine', False)]
        # At least today's instance should be scheduled in [100, 200]
        scheduled = [t for t in routine_tasks if solver.value(t.presence_var)]
        self.assertGreater(len(scheduled), 0, "At least one routine instance should be scheduled")

        for task in scheduled:
            start = solver.value(task.start_var)
            end = solver.value(task.end_var)
            # Must not overlap with [0,100] or [200,30000]
            self.assertGreaterEqual(start, 100, f"Routine starts at {start}, but block ends at 100")
            self.assertLessEqual(end, 200, f"Routine ends at {end}, but block starts at 200")

    def test_fixed_routine_blocks_time_for_other_tasks(self):
        """
        A fixed routine creates a TimeBlock. A user task must not be scheduled
        in that blocked slot.
        """
        routine = Routine(
            name="Gym", type="fixed", repeat="daily",
            duration=60, time="11:00"
        )
        # A task that could fit at 11:00 but shouldn't because the routine blocks it
        task = Task(name="Work", duration=60, break_duration=0)
        task.deadline_min = None

        now = datetime(2026, 7, 6, 10, 0)

        solver, all_tasks, _ = self._expand_and_solve(
            [routine], user_tasks=[task], now=now
        )

        self.assertTrue(solver.value(task.presence_var), "Task should be scheduled")
        task_start = solver.value(task.start_var)
        task_end = solver.value(task.end_var)

        # 11:00 is 60 min from 10:00, so the block is [60, 120]
        gym_start = 60
        gym_end = 120
        # Task must not overlap with the gym block
        self.assertTrue(
            task_end <= gym_start or task_start >= gym_end,
            f"Task [{task_start}, {task_end}] overlaps with fixed routine [{gym_start}, {gym_end}]"
        )

    def test_flexible_routine_displaces_low_priority_task(self):
        """
        When time is scarce, a high-priority flexible routine should be scheduled
        over a low-priority user task.
        """
        routine = Routine(
            name="Critical", type="flexible", repeat="daily",
            duration=50, priority=10, deadline_time="23:59"
        )
        low_task = Task(name="Optional", duration=50, priority=1, break_duration=0)
        low_task.deadline_min = None

        # Only 50 min free → only one of the two can fit
        time_blocks = [
            TimeBlock(start=0, end=100, daily=False),
            TimeBlock(start=150, end=30000, daily=False)
        ]
        now = datetime(2026, 7, 6, 10, 0)

        solver, all_tasks, _ = self._expand_and_solve(
            [routine], user_tasks=[low_task], time_blocks=time_blocks, now=now
        )

        routine_tasks = [t for t in all_tasks if getattr(t, 'is_routine', False)]
        # At least one routine instance should win
        routine_scheduled = any(solver.value(t.presence_var) for t in routine_tasks)
        low_scheduled = solver.value(low_task.presence_var)

        # With priority 10 (high tier) vs 1 (low tier), the routine should dominate
        if not routine_scheduled and low_scheduled:
            self.fail("High-priority routine should be preferred over low-priority task")

    def test_multiple_routines_and_tasks_solver_finds_solution(self):
        """
        A mix of fixed and flexible routines plus regular tasks should all solve together.
        """
        fixed_routine = Routine(
            name="Gym", type="fixed", repeat="daily",
            duration=60, time="07:00"
        )
        flex_routine = Routine(
            name="Study", type="flexible", repeat="daily",
            duration=30, priority=5, deadline_time="18:00", break_duration=5
        )
        task = Task(name="Project", duration=120, break_duration=10)
        task.deadline_min = None

        now = datetime(2026, 7, 6, 10, 0)

        solver, all_tasks, routine_info = self._expand_and_solve(
            [fixed_routine, flex_routine], user_tasks=[task], now=now
        )

        # The regular task should be scheduled
        self.assertTrue(solver.value(task.presence_var), "Regular task should be scheduled")

        # At least some routine instances should be scheduled
        routine_tasks = [t for t in all_tasks if getattr(t, 'is_routine', False)]
        scheduled_routines = sum(1 for t in routine_tasks if solver.value(t.presence_var))
        self.assertGreater(scheduled_routines, 0, "Some flexible routines should be scheduled")

        # routine_info should contain both types
        types_present = {r["type"] for r in routine_info}
        self.assertIn("fixed", types_present)
        self.assertIn("flexible", types_present)

    def test_flexible_routine_respects_break_duration(self):
        """
        A flexible routine with break_duration should enforce the gap between itself
        and other tasks, just like a regular task's break.
        """
        routine = Routine(
            name="Read", type="flexible", repeat="daily",
            duration=30, priority=5, deadline_time="23:59", break_duration=15
        )
        task = Task(name="Code", duration=30, break_duration=0)
        task.deadline_min = None

        now = datetime(2026, 7, 6, 10, 0)

        solver, all_tasks, _ = self._expand_and_solve(
            [routine], user_tasks=[task], now=now
        )

        routine_tasks = [t for t in all_tasks if getattr(t, 'is_routine', False) and solver.value(t.presence_var)]
        self.assertTrue(solver.value(task.presence_var))

        # Check that the routine's break is respected with the regular task
        task_start = solver.value(task.start_var)
        task_end = solver.value(task.end_var)

        for rt in routine_tasks:
            rt_start = solver.value(rt.start_var)
            rt_end = solver.value(rt.end_var)

            if rt_start < task_start:
                # Routine comes before task → must respect routine's break
                self.assertGreaterEqual(
                    task_start, rt_end + rt.break_duration,
                    f"Task starts at {task_start} but routine ends at {rt_end} with break {rt.break_duration}"
                )
            elif task_start < rt_start:
                # Task comes before routine → must respect task's break
                self.assertGreaterEqual(
                    rt_start, task_end + task.break_duration,
                    f"Routine starts at {rt_start} but task ends at {task_end} with break {task.break_duration}"
                )

    def test_no_routines_solver_still_works(self):
        """
        When routines list is empty, the solver should work exactly as before.
        """
        task = Task(name="Solo", duration=60, break_duration=0)
        task.deadline_min = None

        solver, all_tasks, routine_info = self._expand_and_solve(
            [], user_tasks=[task]
        )

        self.assertTrue(solver.value(task.presence_var))
        self.assertEqual(len(routine_info), 0)
        self.assertEqual(len([t for t in all_tasks if getattr(t, 'is_routine', False)]), 0)

    def test_flexible_routine_does_not_start_before_its_day(self):
        """
        A flexible routine generated for tomorrow should not be scheduled today,
        even if there is free time today.
        """
        routine = Routine(
            name="TomorrowTask", type="flexible", repeat="daily",
            duration=60, priority=5, deadline_time="23:59"
        )
        
        # now is 10:00 on Day 0
        now = datetime(2026, 7, 6, 10, 0)
        
        # We only want to test tomorrow's instance. 
        # expand_routines will generate one for today and one for tomorrow.
        # Let's check tomorrow's instance specifically.
        solver, all_tasks, _ = self._expand_and_solve(
            [routine], now=now, max_horizon_days=2
        )
        
        tomorrow_tasks = [t for t in all_tasks if getattr(t, 'is_routine', False) and "(07.07)" in t.name]
        self.assertGreater(len(tomorrow_tasks), 0, "Tomorrow's routine should be generated")
        
        tomorrow_task = tomorrow_tasks[0]
        
        self.assertTrue(solver.value(tomorrow_task.presence_var), "Tomorrow's routine should be scheduled")
        
        start_time = solver.value(tomorrow_task.start_var)
        
        # Tomorrow starts at midnight.
        # now is 2026-07-06 10:00. Midnight of 07.07 is 14 hours from now (14 * 60 = 840 minutes)
        minutes_to_midnight = 14 * 60
        
        self.assertGreaterEqual(
            start_time, minutes_to_midnight,
            f"Tomorrow's routine scheduled too early! Started at {start_time}, but midnight is {minutes_to_midnight}"
        )


if __name__ == '__main__':
    unittest.main()

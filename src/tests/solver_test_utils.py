import unittest
from ortools.sat.python import cp_model
from restrictions import create_model

class BaseSolverTest(unittest.TestCase):
    """
    Base test class providing helper methods and shared configuration 
    for solving and validating CP-SAT scheduling models.
    """

    def _solve(self, tasks, time_blocks=None):
        """
        Helper: builds the model, solves it, and asserts a valid solution was found.
        Returns the solver instance for further assertions.
        """
        if time_blocks is None:
            time_blocks = []
        model = create_model(tasks, time_blocks)
        solver = cp_model.CpSolver()
        
        # Test infrastructure limits
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 1
        
        status = solver.solve(model)
        self.assertIn(status, (cp_model.OPTIMAL, cp_model.FEASIBLE),
                      "Solver failed to find a feasible solution")
        self._assert_invariants(solver, tasks, time_blocks)
        return solver

    def _assert_invariants(self, solver, tasks, time_blocks):
        from restrictions import calculate_horizon, generate_blocked_intervals
        horizon = calculate_horizon(tasks)
        
        strict_intervals = []
        blocked = generate_blocked_intervals(time_blocks, horizon)
        for b_start, b_end in blocked:
            strict_intervals.append((b_start, b_end, "Blocked"))
            
        for task in tasks:
            is_present = solver.value(task.presence_var)
            if not is_present:
                if task.chunks:
                    for c in task.chunks:
                        self.assertFalse(solver.value(c['presence_var']), f"Task absent but chunk present for {task.name}")
                        self.assertEqual(solver.value(c['size_var']), 0, f"Task absent but chunk has size > 0 for {task.name}")
                continue
            
            # Deadline invariant: present task must end before its deadline
            if getattr(task, 'deadline_min', None) is not None:
                end = solver.value(task.end_var)
                self.assertLessEqual(end, task.deadline_min, f"Task {task.name} ends at {end} but deadline is {task.deadline_min}")
                
            if not task.chunks:
                start = solver.value(task.start_var)
                end = solver.value(task.end_var)
                self.assertEqual(end - start, task.duration, f"Task {task.name} duration mismatch")
                self.assertGreaterEqual(start, 0, f"Task {task.name} starts before 0")
                self.assertLessEqual(end, horizon, f"Task {task.name} ends after horizon")
                strict_intervals.append((start, end, f"Task {task.name}"))
            else:
                present_chunks = []
                for idx, c in enumerate(task.chunks):
                    if solver.value(c['presence_var']):
                        present_chunks.append((idx, c))
                        start = solver.value(c['start_var'])
                        end = solver.value(c['end_var'])
                        size = solver.value(c['size_var'])
                        self.assertEqual(end - start, size, f"Chunk {idx} of {task.name} size mismatch")
                        self.assertGreaterEqual(start, 0, f"Chunk {idx} of {task.name} starts before 0")
                        self.assertLessEqual(end, horizon, f"Chunk {idx} of {task.name} ends after horizon")
                        strict_intervals.append((start, end, f"Task {task.name} Chunk {idx}"))
                
                total_size = sum(solver.value(c['size_var']) for _, c in present_chunks)
                self.assertEqual(total_size, task.duration, f"Chunk sizes sum mismatch for {task.name}")
                
                indices = [idx for idx, _ in present_chunks]
                self.assertEqual(indices, list(range(len(present_chunks))), f"Chunks have holes in {task.name}")
                
                for i in range(len(present_chunks) - 1):
                    _, c1 = present_chunks[i]
                    _, c2 = present_chunks[i+1]
                    end1 = solver.value(c1['end_var'])
                    start2 = solver.value(c2['start_var'])
                    self.assertGreaterEqual(start2, end1 + task.break_duration, f"Break violated in {task.name} between chunks")
                    
        strict_intervals.sort(key=lambda x: x[0])
        for i in range(len(strict_intervals) - 1):
            curr_start, curr_end, curr_name = strict_intervals[i]
            next_start, next_end, next_name = strict_intervals[i+1]
            # Tasks and blocks must not overlap internally
            self.assertLessEqual(curr_end, next_start, f"Overlap: {curr_name} ({curr_start}-{curr_end}) intersects {next_name} ({next_start}-{next_end})")

    def _get_present_and_absent_chunks(self, solver, task):
        """
        Helper: separates a task's chunks into present and absent lists
        based on the solver's solution.
        """
        present = []
        absent = []
        for chunk in task.chunks:
            if solver.value(chunk['presence_var']):
                present.append(chunk)
            else:
                absent.append(chunk)
        return present, absent

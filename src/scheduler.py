from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from ortools.sat.python import cp_model

from .restrictions import create_model, calculate_horizon
from .data_structs import Task, TimeBlock, Routine
from .utils import process_time_blocks, minutes_to_time
from .routine_expansion import expand_routines


@dataclass
class ScheduledChunk:
    start_time: datetime
    end_time: datetime
    duration: timedelta


@dataclass
class ScheduledTask:
    task: Task
    start_time: datetime
    end_time: datetime
    chunks: list[ScheduledChunk] = field(default_factory=list)


@dataclass
class ScheduledRoutine:
    task: Task
    start_time: datetime
    end_time: datetime


@dataclass
class FixedRoutine:
    name: str
    day: date
    time: str
    duration: timedelta


@dataclass
class FlexibleRoutineInfo:
    name: str
    day: date
    deadline: datetime
    duration: timedelta


@dataclass
class SkippedTask:
    task: Task


class ScheduleResult:
    def __init__(self, status_name: str):
        self.status = status_name
        self.scheduled_tasks: list[ScheduledTask] = []
        self.skipped_tasks: list[SkippedTask] = []
        self.scheduled_routines: list[ScheduledRoutine] = []
        self.fixed_routines: list[FixedRoutine] = []
        self.flexible_routines_info: list[FlexibleRoutineInfo] = []

    @property
    def is_successful(self):
        return self.status in ("OPTIMAL", "FEASIBLE")


class Scheduler:
    def __init__(self, max_horizon_days: int = 14, priority_threshold: int = 10):
        self.max_horizon_days = max_horizon_days
        self.priority_threshold = priority_threshold

        self.tasks: list[Task] = []
        self.time_blocks: list[TimeBlock] = []
        self.routines: list[Routine] = []

    def add_task(self, task: Task):
        self.tasks.append(task)

    def add_time_block(self, time_block: TimeBlock):
        self.time_blocks.append(time_block)

    def add_routine(self, routine: Routine):
        self.routines.append(routine)

    def solve(
        self,
        start_time: datetime | None = None,
        timeout_seconds: float = 0.5,
        max_horizon_days: int | None = None,
        priority_threshold: int | None = None
    ) -> ScheduleResult:
        now = start_time or datetime.now().replace(second=0, microsecond=0)
        
        actual_horizon_days = max_horizon_days if max_horizon_days is not None else self.max_horizon_days
        actual_priority_threshold = priority_threshold if priority_threshold is not None else self.priority_threshold

        # Process deadlines for tasks
        for task in self.tasks:
            if getattr(task, "deadline", None) is not None:
                dt_deadline = task.deadline
                task.deadline_min = int((dt_deadline - now).total_seconds() / 60)
            else:
                task.deadline_min = None

        # Process time blocks
        processed_blocks = process_time_blocks(self.time_blocks, now)

        # Calculate horizon
        horizon = calculate_horizon(self.tasks, max_horizon_days=actual_horizon_days)

        # Expand routines
        extra_tasks, extra_blocks, routine_info = expand_routines(self.routines, now, horizon)

        # Combine base and extra data
        combined_tasks = self.tasks + extra_tasks
        combined_blocks = processed_blocks + extra_blocks

        # Create model
        model = create_model(
            combined_tasks,
            combined_blocks,
            max_horizon_days=actual_horizon_days,
            priority_threshold=actual_priority_threshold,
            horizon=horizon,
        )

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds

        status = solver.solve(model)

        # Parse results
        result = ScheduleResult(
            status_name=(
                "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE" if status == cp_model.FEASIBLE else "INFEASIBLE"
            )
        )

        if result.is_successful:
            for task in combined_tasks:
                if solver.value(task.presence_var):
                    start_val = solver.value(task.start_var)
                    end_val = solver.value(task.end_var)
                    start_time_str = minutes_to_time(start_val, now)
                    end_time_str = minutes_to_time(end_val, now)

                    if getattr(task, "is_routine", False):
                        result.scheduled_routines.append(ScheduledRoutine(task, start_time_str, end_time_str))
                    else:
                        scheduled_task = ScheduledTask(task, start_time_str, end_time_str)
                        if task.chunks:
                            for chunk in task.chunks:
                                if solver.value(chunk["presence_var"]):
                                    cs = minutes_to_time(solver.value(chunk["start_var"]), now)
                                    ce = minutes_to_time(solver.value(chunk["end_var"]), now)
                                    csize = solver.value(chunk["size_var"])
                                    scheduled_task.chunks.append(ScheduledChunk(cs, ce, timedelta(minutes=csize)))
                        result.scheduled_tasks.append(scheduled_task)
                else:
                    if not getattr(task, "is_routine", False):
                        result.skipped_tasks.append(SkippedTask(task))

            if routine_info:
                for r in routine_info:
                    if r["type"] == "fixed":
                        result.fixed_routines.append(FixedRoutine(r["name"], r["day"], r["time"], r["duration"]))
                    elif r["type"] == "flexible":
                        result.flexible_routines_info.append(
                            FlexibleRoutineInfo(r["name"], r["day"], r["deadline"], r["duration"])
                        )

        return result

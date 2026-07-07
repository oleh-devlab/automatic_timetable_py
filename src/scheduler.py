import math
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
    routine_type: str = "flexible"


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
    def __init__(self, packer_status_name: str, gravity_status_name: str | None = None):
        self.packer_status = packer_status_name
        self.gravity_status = gravity_status_name
        if gravity_status_name:
            self.status = f"{packer_status_name} (Packer) / {gravity_status_name} (Gravity)"
        else:
            self.status = packer_status_name

        self.scheduled_tasks: list[ScheduledTask] = []
        self.skipped_tasks: list[SkippedTask] = []
        self.scheduled_routines: list[ScheduledRoutine] = []
        self.skipped_routines: list[SkippedTask] = []
        self.flexible_routines_info: list[FlexibleRoutineInfo] = []
        self.horizon: int = 0

    @property
    def is_successful(self):
        return self.packer_status in ("OPTIMAL", "FEASIBLE")


class Scheduler:
    def __init__(self, min_horizon_days: int = 14, priority_threshold: int = 5, step_minutes: int = 1):
        self.min_horizon_days = min_horizon_days
        self.priority_threshold = priority_threshold
        self.step_minutes = step_minutes

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
        min_horizon_days: int | None = None,
        priority_threshold: int | None = None,
        num_search_workers: int = 1,
        max_memory_in_mb: int = 256,
    ) -> ScheduleResult:
        now = start_time or datetime.now().replace(second=0, microsecond=0)

        # Round 'now' UP (ceil) to the nearest step_minutes
        if self.step_minutes > 1:
            minute_remainder = now.minute % self.step_minutes
            if minute_remainder != 0:
                minutes_to_add = self.step_minutes - minute_remainder
                now += timedelta(minutes=minutes_to_add)

        actual_horizon_days = min_horizon_days if min_horizon_days is not None else self.min_horizon_days
        actual_priority_threshold = priority_threshold if priority_threshold is not None else self.priority_threshold

        # Process deadlines and duration for tasks
        for task in self.tasks:
            task.duration_steps = math.ceil(task.duration.total_seconds() / 60 / self.step_minutes)
            task.break_duration_steps = math.ceil(task.break_duration.total_seconds() / 60 / self.step_minutes)
            if task.min_chunk_duration:
                task.min_chunk_duration_steps = math.ceil(
                    task.min_chunk_duration.total_seconds() / 60 / self.step_minutes
                )
            if task.max_chunk_duration:
                task.max_chunk_duration_steps = math.ceil(
                    task.max_chunk_duration.total_seconds() / 60 / self.step_minutes
                )

            if getattr(task, "deadline", None) is not None:
                dt_deadline = task.deadline
                task.deadline_steps = math.floor((dt_deadline - now).total_seconds() / 60 / self.step_minutes)
            else:
                task.deadline_steps = None

        # Process routines duration
        for routine in self.routines:
            routine.duration_steps = math.ceil(routine.duration.total_seconds() / 60 / self.step_minutes)
            routine.break_duration_steps = math.ceil(routine.break_duration.total_seconds() / 60 / self.step_minutes)

        # Process time blocks
        processed_blocks = process_time_blocks(self.time_blocks, now, self.step_minutes)

        # Calculate horizon
        horizon = calculate_horizon(self.tasks, min_horizon_days=actual_horizon_days, step_minutes=self.step_minutes)

        # Expand routines
        extra_tasks, extra_blocks, routine_info = expand_routines(self.routines, now, horizon, self.step_minutes)

        # Combine base and extra data
        combined_tasks = self.tasks + extra_tasks
        combined_blocks = processed_blocks + extra_blocks

        # Create model
        model = create_model(
            combined_tasks,
            combined_blocks,
            min_horizon_days=actual_horizon_days,
            priority_threshold=actual_priority_threshold,
            horizon=horizon,
            step_minutes=self.step_minutes,
        )

        # Stage 1: Packer
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = timeout_seconds
        solver.parameters.num_search_workers = num_search_workers
        solver.parameters.max_memory_in_mb = max_memory_in_mb

        packer_status = solver.solve(model)
        gravity_status = None

        if packer_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # Stage 2: Gravity
            # 1. Lock the presence variables based on Stage 1 solution
            for task in combined_tasks:
                if hasattr(task, "presence_var"):
                    val = solver.value(task.presence_var)
                    model.add(task.presence_var == val)
                if getattr(task, "chunks", None):
                    for chunk in task.chunks:
                        val = solver.value(chunk["presence_var"])
                        model.add(chunk["presence_var"] == val)

            # 2. Set new objective for time placement
            if hasattr(model, "time_bonus_terms"):
                model.maximize(sum(model.time_bonus_terms))

                # Re-solve (reusing the same solver instance limits time globally)
                gravity_status = solver.solve(model)

        packer_str = solver.status_name(packer_status)
        gravity_str = solver.status_name(gravity_status) if gravity_status is not None else None

        result = ScheduleResult(packer_status_name=packer_str, gravity_status_name=gravity_str)
        result.horizon = horizon * self.step_minutes

        if result.is_successful:
            for task in combined_tasks:
                if solver.value(task.presence_var):
                    start_val = solver.value(task.start_var) * self.step_minutes
                    end_val = solver.value(task.end_var) * self.step_minutes
                    start_time_str = minutes_to_time(start_val, now)
                    end_time_str = minutes_to_time(end_val, now)

                    if getattr(task, "is_routine", False):
                        result.scheduled_routines.append(
                            ScheduledRoutine(task, start_time_str, end_time_str, routine_type="flexible")
                        )
                    else:
                        scheduled_task = ScheduledTask(task, start_time_str, end_time_str)
                        if task.chunks:
                            for chunk in task.chunks:
                                if solver.value(chunk["presence_var"]):
                                    c_start = solver.value(chunk["start_var"]) * self.step_minutes
                                    c_end = solver.value(chunk["end_var"]) * self.step_minutes
                                    csize = solver.value(chunk["size_var"]) * self.step_minutes
                                    cs = minutes_to_time(c_start, now)
                                    ce = minutes_to_time(c_end, now)
                                    scheduled_task.chunks.append(ScheduledChunk(cs, ce, timedelta(minutes=csize)))
                        result.scheduled_tasks.append(scheduled_task)
                else:
                    if not getattr(task, "is_routine", False):
                        result.skipped_tasks.append(SkippedTask(task))
                    else:
                        result.skipped_routines.append(SkippedTask(task))

            if routine_info:
                for r in routine_info:
                    if r["type"] == "fixed":
                        t_val = r["time"].time() if hasattr(r["time"], "time") else r["time"]
                        if isinstance(t_val, str):
                            t_val = datetime.strptime(t_val, "%H:%M").time()
                        rt_start = datetime.combine(r["day"], t_val, tzinfo=now.tzinfo)
                        rt_end = rt_start + r["duration"]

                        dummy_task = Task(name=r["name"], duration=r["duration"])
                        dummy_task.is_routine = True

                        result.scheduled_routines.append(
                            ScheduledRoutine(dummy_task, rt_start, rt_end, routine_type="fixed")
                        )
                    elif r["type"] == "flexible":
                        result.flexible_routines_info.append(
                            FlexibleRoutineInfo(r["name"], r["day"], r["deadline"], r["duration"])
                        )

        return result

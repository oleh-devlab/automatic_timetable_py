from datetime import datetime
import math
from .data_structs import Task, TimeBlock
from .utils import iter_active_dates


def expand_routines(routines, now, horizon_minutes, step_minutes=1):
    """
    Expands routines into concrete Tasks and TimeBlocks over the planning horizon.

    Args:
        routines (list[Routine]): List of user-defined routines.
        now (datetime): Current time.
        horizon_minutes (int): Planning horizon in minutes (steps).
        step_minutes (int): Minutes per step.

    Returns:
        tuple: (extra_tasks, extra_blocks, routine_info)
            - extra_tasks: list[Task] (for flexible routines)
            - extra_blocks: list[TimeBlock] (for fixed routines)
            - routine_info: list[dict] (metadata for output)
    """
    extra_tasks = []
    extra_blocks = []
    routine_info = []

    for routine in routines:
        # Check which days this routine applies to
        weekdays = None
        if routine.repeat == "weekly":
            if not routine.weekdays:
                continue  # a weekly routine without weekdays never applies
            weekdays = routine.weekdays

        # Start a day early: a fixed routine that began yesterday may still be running at `now`
        for current_date in iter_active_dates(
            now, horizon_minutes, step_minutes, weekdays=weekdays, start_day_offset=-1
        ):
            # Check if routine should be skipped
            if getattr(routine, "resume_after", None) and current_date <= routine.resume_after:
                continue

            # It's a valid day for this routine
            if routine.type == "fixed":
                if not routine.time:
                    continue  # Invalid fixed routine

                t_val = routine.time.time() if hasattr(routine.time, "time") else routine.time
                routine_dt = datetime.combine(current_date, t_val, tzinfo=now.tzinfo)

                start_steps = math.floor(((routine_dt - now).total_seconds() / 60) / step_minutes)
                end_steps = start_steps + routine.duration_steps

                if end_steps > 0 and start_steps <= horizon_minutes:
                    extra_blocks.append(
                        TimeBlock(start_steps, end_steps, daily=False, name=routine.name, id=routine.id)
                    )
                    routine_info.append(
                        {
                            "name": routine.name,
                            "day": current_date,
                            "time": routine.time,
                            "type": "fixed",
                            "duration": routine.duration,
                            "id": routine.id,
                        }
                    )

            elif routine.type == "flexible":
                if routine.deadline_time:
                    t_val = (
                        routine.deadline_time.time()
                        if hasattr(routine.deadline_time, "time")
                        else routine.deadline_time
                    )
                    deadline_dt = datetime.combine(current_date, t_val, tzinfo=now.tzinfo)
                else:
                    dt_str = f"{current_date.strftime('%Y-%m-%d')} 23:59"
                    deadline_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
                deadline_steps = math.floor(((deadline_dt - now).total_seconds() / 60) / step_minutes)

                # Only include if the deadline is in the future
                # and it's within our horizon
                if deadline_steps > 0 and deadline_steps - routine.duration_steps <= horizon_minutes:
                    # We do NOT use Pomodoro chunking for routines, so we don't set min/max chunk duration.
                    t = Task(
                        name=routine.name,
                        duration=routine.duration,
                        deadline=deadline_dt,
                        priority=routine.priority,
                        break_duration=routine.break_duration,
                    )
                    t.id = f"r_{routine.id}_{current_date}" if routine.id else None
                    t.routine_id = routine.id
                    t.depends_on = [f"r_{d}_{current_date}" for d in routine.depends_on] if routine.depends_on else []
                    # Pre-calculate deadline_steps so solver doesn't have to parse it
                    t.deadline_steps = deadline_steps
                    t.duration_steps = routine.duration_steps
                    t.break_duration_steps = routine.break_duration_steps
                    t.is_routine = True

                    start_of_day_dt = datetime(
                        current_date.year, current_date.month, current_date.day, tzinfo=now.tzinfo
                    )
                    start_steps = math.floor(((start_of_day_dt - now).total_seconds() / 60) / step_minutes)
                    t.start_steps = max(0, start_steps)

                    extra_tasks.append(t)
                    routine_info.append(
                        {
                            "name": routine.name,
                            "day": current_date,
                            "deadline": deadline_dt,
                            "type": "flexible",
                            "duration": routine.duration,
                            "id": routine.id,
                        }
                    )

    return extra_tasks, extra_blocks, routine_info

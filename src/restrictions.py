from ortools.sat.python import cp_model

from .utils import merge_time_blocks
from .chunking import calculate_chunks
from .data_structs import TimeBlock


def calculate_horizon(user_tasks, max_horizon_days=14):
    if max_horizon_days <= 0:
        raise ValueError(f"max_horizon_days must be greater than 0, got {max_horizon_days}")
    """
    Calculates the safe planning horizon (maximum available time in minutes).
    
    Args:
        user_tasks (list[Task]): List of user tasks.
        max_horizon_days (int, optional): Maximum horizon limit in days.
        
    Returns:
        int: Planning horizon in minutes.
    """
    base_horizon = sum(task.duration for task in user_tasks)
    max_deadline = max((t.deadline_min for t in user_tasks if getattr(t, "deadline_min", None) is not None), default=0)
    return max(base_horizon * 3 + 1440, max_horizon_days * 1440, max_deadline)


def generate_blocked_intervals(time_blocks, horizon):
    """
    Generates the final list of blocked time intervals (in minutes).
    For daily blocks, clones are created up to the end of the horizon.
    All intervals are clamped to zero on the left (to avoid going into the past) and merged.

    Args:
        time_blocks (list[TimeBlock]): Original time blocks (from JSON).
        horizon (int): Planning horizon in minutes.

    Returns:
        list[tuple[int, int]]: List of non-overlapping intervals in the format (start, end).
    """
    actual_blocks = []
    for tb in time_blocks:
        if tb.daily:
            curr_start = tb.start
            curr_end = tb.end
            while curr_start < horizon:
                clamped_start = max(0, curr_start)
                if curr_end > 0:
                    actual_blocks.append(TimeBlock(clamped_start, curr_end, daily=False))
                curr_start += 1440
                curr_end += 1440
        else:
            if tb.start >= horizon:
                continue
            clamped_start = max(0, tb.start)
            if tb.end > 0:
                actual_blocks.append(TimeBlock(clamped_start, tb.end, daily=False))

    # Merge all overlapping intervals into one continuous list
    return [(block.start, block.end) for block in merge_time_blocks(actual_blocks)]


def calculate_task_weight(task, priority_threshold=10):
    """
    Calculates the task weight for the objective function based on a 2-Tier logic.
    High tier tasks (priority >= priority_threshold) absolutely dominate.
    Inside each tier, deadlines dominate over priority.
    """
    deadline_days = task.deadline_min // 1440 if getattr(task, "deadline_min", None) is not None else 3650
    days_inverted = max(0, 3650 - deadline_days)

    if task.priority >= priority_threshold:
        return 100_000_000 + (days_inverted * 10_000) + task.priority
    else:
        return 10_000 + (days_inverted * 10) + task.priority


def create_model(user_tasks, time_blocks, max_horizon_days=14, priority_threshold=10, horizon=None):
    model = cp_model.CpModel()

    # Data preparation and calculation of constraints
    if horizon is None:
        horizon = calculate_horizon(user_tasks, max_horizon_days)

    blocked_time_intervals = generate_blocked_intervals(time_blocks, horizon)

    # Create variables for blocked periods (fixed intervals)
    time_blocks_vars = []
    for i, (start, end) in enumerate(blocked_time_intervals):
        fixed_interval = model.new_fixed_size_interval_var(start, end - start, f"blocked_{i+1}")
        time_blocks_vars.append(fixed_interval)

    strict_intervals = list(time_blocks_vars)
    extended_intervals = []

    # Create variables for each user task
    for i, task in enumerate(user_tasks):
        needs_chunking = task.min_chunk_duration is not None and task.duration > task.min_chunk_duration

        if needs_chunking:
            max_chunks = calculate_chunks(
                task.duration,
                task.min_chunk_duration,
                task.max_chunk_duration,
            )

            task.presence_var = model.new_bool_var(f"presence_task_{i}")

            for c in range(max_chunks):
                chunk = {}
                chunk["start_var"] = model.new_int_var(task.start_min, horizon, f"start_{i}_chunk_{c}")
                chunk["end_var"] = model.new_int_var(task.start_min, horizon, f"end_{i}_chunk_{c}")
                chunk["size_var"] = model.new_int_var(0, task.max_chunk_duration, f"size_{i}_chunk_{c}")
                chunk["presence_var"] = model.new_bool_var(f"presence_{i}_chunk_{c}")

                chunk["interval_var"] = model.new_optional_interval_var(
                    chunk["start_var"],
                    chunk["size_var"],
                    chunk["end_var"],
                    chunk["presence_var"],
                    f"task_{task.name}_chunk_{c}",
                )

                task.chunks.append(chunk)
                strict_intervals.append(chunk["interval_var"])

                ext_size = model.new_int_var(
                    0, task.max_chunk_duration + task.break_duration, f"ext_size_{i}_chunk_{c}"
                )
                model.add(ext_size == chunk["size_var"] + task.break_duration).only_enforce_if(chunk["presence_var"])
                model.add(ext_size == 0).only_enforce_if(chunk["presence_var"].negated())

                ext_end = model.new_int_var(0, horizon * 2, f"ext_end_{i}_chunk_{c}")
                model.add(ext_end == chunk["start_var"] + ext_size).only_enforce_if(chunk["presence_var"])

                chunk["extended_interval_var"] = model.new_optional_interval_var(
                    chunk["start_var"], ext_size, ext_end, chunk["presence_var"], f"ext_task_{i}_chunk_{c}"
                )
                extended_intervals.append(chunk["extended_interval_var"])

            for c, chunk in enumerate(task.chunks):
                model.add(chunk["size_var"] == 0).only_enforce_if(chunk["presence_var"].negated())
                model.add(chunk["size_var"] > 0).only_enforce_if(chunk["presence_var"])

                model.add_implication(chunk["presence_var"], task.presence_var)

                if c > 0:
                    prev_chunk = task.chunks[c - 1]
                    model.add_implication(chunk["presence_var"], prev_chunk["presence_var"])

                    model.add(chunk["start_var"] >= prev_chunk["end_var"] + task.break_duration).only_enforce_if(
                        chunk["presence_var"]
                    )

                if c < max_chunks - 1:
                    next_chunk = task.chunks[c + 1]

                    model.add(chunk["size_var"] >= task.min_chunk_duration).only_enforce_if(next_chunk["presence_var"])

            model.add(sum(chunk["size_var"] for chunk in task.chunks) == task.duration).only_enforce_if(
                task.presence_var
            )

            for chunk in task.chunks:
                model.add_implication(task.presence_var.negated(), chunk["presence_var"].negated())

            # We keep the start/end values to ensure compatibility
            task.start_var = task.chunks[0]["start_var"]
            task.end_var = task.chunks[-1]["end_var"]

        else:
            task.start_var = model.new_int_var(task.start_min, horizon, f"start_{i}")
            task.end_var = model.new_int_var(task.start_min, horizon, f"end_{i}")
            task.presence_var = model.new_bool_var(f"presence_{i}")
            task.interval_var = model.new_optional_interval_var(
                task.start_var, task.duration, task.end_var, task.presence_var, f"task_{task.name}_interval"
            )
            strict_intervals.append(task.interval_var)

            # Extended interval for global breaks (even for tasks without chunks)
            ext_size = model.new_int_var(0, task.duration + task.break_duration, f"ext_size_{i}")
            model.add(ext_size == task.duration + task.break_duration).only_enforce_if(task.presence_var)
            model.add(ext_size == 0).only_enforce_if(task.presence_var.negated())

            ext_end = model.new_int_var(0, horizon * 2, f"ext_end_{i}")
            model.add(ext_end == task.start_var + ext_size).only_enforce_if(task.presence_var)

            task.extended_interval_var = model.new_optional_interval_var(
                task.start_var, ext_size, ext_end, task.presence_var, f"ext_task_{i}"
            )
            extended_intervals.append(task.extended_interval_var)

    # Tasks and blocked periods cannot overlap
    model.add_no_overlap(strict_intervals)

    # Tasks, including their breaks, cannot overlap with other tasks
    model.add_no_overlap(extended_intervals)

    # Deadline constraints
    for task in user_tasks:
        if getattr(task, "deadline_min", None) is not None:
            if task.chunks:
                # Apply to every chunk — since chunks are ordered,
                # this ensures the last present chunk ends before the deadline
                for chunk in task.chunks:
                    model.add(chunk["end_var"] <= task.deadline_min).only_enforce_if(chunk["presence_var"])
            else:
                model.add(task.end_var <= task.deadline_min).only_enforce_if(task.presence_var)

    # Maximize the weighted sum of scheduled tasks
    objective_terms = []
    for task in user_tasks:
        weight = calculate_task_weight(task, priority_threshold)
        objective_terms.append(task.presence_var * weight)

    model.maximize(sum(objective_terms))

    return model

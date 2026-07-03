from ortools.sat.python import cp_model

from .utils import merge_time_blocks
from .chunking import calculate_chunks
from .data_structs import TimeBlock


def calculate_horizon(user_tasks, max_horizon_days=14, step_minutes=1):
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
    steps_per_day = 1440 // step_minutes
    base_horizon = sum(task.duration_steps for task in user_tasks)
    max_deadline = max((t.deadline_steps for t in user_tasks if getattr(t, "deadline_steps", None) is not None), default=0)
    return max(base_horizon * 3 + steps_per_day, max_horizon_days * steps_per_day, max_deadline)


def generate_blocked_intervals(time_blocks, horizon, step_minutes=1):
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
    steps_per_day = 1440 // step_minutes
    actual_blocks = []
    for tb in time_blocks:
        if tb.daily:
            curr_start = tb.start
            curr_end = tb.end
            while curr_start < horizon:
                clamped_start = max(0, curr_start)
                if curr_end > 0:
                    actual_blocks.append(TimeBlock(clamped_start, curr_end, daily=False))
                curr_start += steps_per_day
                curr_end += steps_per_day
        else:
            if tb.start >= horizon:
                continue
            clamped_start = max(0, tb.start)
            if tb.end > 0:
                actual_blocks.append(TimeBlock(clamped_start, tb.end, daily=False))

    # Merge all overlapping intervals into one continuous list
    return [(block.start, block.end) for block in merge_time_blocks(actual_blocks)]


def calculate_task_weight(task, priority_threshold=5, step_minutes=1):
    """
    Calculates the task weight for the objective function based on a 2-Tier logic.
    High tier tasks (priority >= priority_threshold) absolutely dominate.
    Inside each tier, deadlines dominate over priority.
    """
    priority_step = 1
    deadline_step = 15 
    
    max_deadline_bonus = 3650 * deadline_step
    
    low_tier_base = 60000
    high_tier_base = low_tier_base * 1000

    steps_per_day = 1440 // step_minutes
    deadline_days = task.deadline_steps // steps_per_day if getattr(task, "deadline_steps", None) is not None else 3650
    days_inverted = max(0, 3650 - deadline_days)
    
    weighted_priority = task.priority * priority_step

    if task.priority >= priority_threshold:
        return high_tier_base + (days_inverted * deadline_step) + weighted_priority
    else:
        return low_tier_base + (days_inverted * deadline_step) + weighted_priority


def create_model(user_tasks, time_blocks, max_horizon_days=14, priority_threshold=5, horizon=None, step_minutes=1):
    model = cp_model.CpModel()

    # Data preparation and calculation of constraints
    if horizon is None:
        horizon = calculate_horizon(user_tasks, max_horizon_days, step_minutes)

    blocked_time_intervals = generate_blocked_intervals(time_blocks, horizon, step_minutes)

    # Create variables for blocked periods (fixed intervals)
    time_blocks_vars = []
    for i, (start, end) in enumerate(blocked_time_intervals):
        fixed_interval = model.new_fixed_size_interval_var(start, end - start, f"blocked_{i+1}")
        time_blocks_vars.append(fixed_interval)

    strict_intervals = list(time_blocks_vars)
    extended_intervals = []

    # Create variables for each user task
    for i, task in enumerate(user_tasks):
        task_upper_bound = horizon
        if getattr(task, "deadline_steps", None) is not None:
            task_upper_bound = min(horizon, max(task.start_steps, task.deadline_steps))

        needs_chunking = task.min_chunk_duration_steps is not None and task.duration_steps > task.min_chunk_duration_steps

        if needs_chunking:
            max_chunks = calculate_chunks(
                task.duration,
                task.min_chunk_duration,
                task.max_chunk_duration,
            )

            task.presence_var = model.new_bool_var(f"presence_task_{i}")

            for c in range(max_chunks):
                chunk = {}
                chunk["start_var"] = model.new_int_var(task.start_steps, task_upper_bound, f"start_{i}_chunk_{c}")
                chunk["end_var"] = model.new_int_var(task.start_steps, task_upper_bound, f"end_{i}_chunk_{c}")
                chunk["size_var"] = model.new_int_var(0, task.max_chunk_duration_steps, f"size_{i}_chunk_{c}")
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
                    0, task.max_chunk_duration_steps + task.break_duration_steps, f"ext_size_{i}_chunk_{c}"
                )
                model.add(ext_size == chunk["size_var"] + task.break_duration_steps).only_enforce_if(chunk["presence_var"])
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

                    model.add(chunk["start_var"] >= prev_chunk["end_var"] + task.break_duration_steps).only_enforce_if(
                        chunk["presence_var"]
                    )

                if c < max_chunks - 1:
                    next_chunk = task.chunks[c + 1]

                    model.add(chunk["size_var"] >= task.min_chunk_duration_steps).only_enforce_if(next_chunk["presence_var"])

            model.add(sum(c["size_var"] for c in task.chunks) == task.duration_steps).only_enforce_if(
                task.presence_var
            )

            for chunk in task.chunks:
                model.add_implication(task.presence_var.negated(), chunk["presence_var"].negated())

            # We keep the start/end values to ensure compatibility
            task.start_var = task.chunks[0]["start_var"]
            
            actual_chunk_ends = []
            for c, chunk in enumerate(task.chunks):
                actual_end = model.new_int_var(0, task_upper_bound, f"actual_end_{i}_chunk_{c}")
                model.add(actual_end == chunk["end_var"]).only_enforce_if(chunk["presence_var"])
                model.add(actual_end == 0).only_enforce_if(chunk["presence_var"].negated())
                actual_chunk_ends.append(actual_end)
                
            task.end_var = model.new_int_var(0, task_upper_bound, f"task_end_{i}")
            model.add_max_equality(task.end_var, actual_chunk_ends)

        else:
            task.start_var = model.new_int_var(task.start_steps, task_upper_bound, f"start_{i}")
            task.end_var = model.new_int_var(task.start_steps, task_upper_bound, f"end_{i}")
            task.presence_var = model.new_bool_var(f"presence_{i}")
            task.interval_var = model.new_optional_interval_var(
                task.start_var, task.duration_steps, task.end_var, task.presence_var, f"task_interval_{i}"
            )
            strict_intervals.append(task.interval_var)

            # Extended interval for global breaks (even for tasks without chunks)
            ext_size = model.new_int_var(0, task.duration_steps + task.break_duration_steps, f"ext_size_{i}")
            model.add(ext_size == task.duration_steps + task.break_duration_steps).only_enforce_if(task.presence_var)
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
        if getattr(task, "deadline_steps", None) is not None:
            if task.chunks:
                # Apply to every chunk — since chunks are ordered,
                # this ensures the last present chunk ends before the deadline
                for chunk in task.chunks:
                    model.add(chunk["end_var"] <= task.deadline_steps).only_enforce_if(chunk["presence_var"])
            else:
                model.add(task.end_var <= task.deadline_steps).only_enforce_if(task.presence_var)

    # Stage 1: Packer objective (only fixed weight)
    presence_terms = []
    
    # Stage 2: Gravity objective (time bonuses)
    time_bonus_terms = []

    for i, task in enumerate(user_tasks):
        fixed_weight = calculate_task_weight(task, priority_threshold, step_minutes)
        presence_terms.append(task.presence_var * fixed_weight)
        
        # 3. Force avoiding unnecessary splits (Micro-penalty in Stage 1)
        if getattr(task, "chunks", None):
            for c, chunk in enumerate(task.chunks):
                presence_terms.append(chunk["presence_var"] * -1)
        
        gravity_multiplier = (task.priority ** 3) 
        
        # 1. Pull the entire task to the left (Bonus)
        task_gravity = model.new_int_var(0, horizon, f'task_gravity_{i}')
        model.add(task_gravity == horizon - task.start_var).only_enforce_if(task.presence_var)
        model.add(task_gravity == 0).only_enforce_if(task.presence_var.negated())
        time_bonus_terms.append(task_gravity * (gravity_multiplier * 1000))
        
        # 2. Force chunks to stick together (Penalty for GAPS)
        task_gaps = model.new_int_var(0, horizon, f'task_gaps_{i}')
        model.add(task_gaps == (task.end_var - task.start_var) - task.duration_steps).only_enforce_if(task.presence_var)
        model.add(task_gaps == 0).only_enforce_if(task.presence_var.negated())
        time_bonus_terms.append(task_gaps * (-gravity_multiplier * 10))
        
    # Set objective for Stage 1
    model.maximize(sum(presence_terms))
    
    # Attach Stage 2 terms to the model for scheduler.py
    model.time_bonus_terms = time_bonus_terms

    return model

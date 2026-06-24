from ortools.sat.python import cp_model

from utils import merge_time_blocks

def calculate_horizon(user_tasks, max_horizon_days=14):
    """
    Calculates the safe planning horizon (maximum available time in minutes).
    
    Args:
        user_tasks (list[Task]): List of user tasks.
        max_horizon_days (int, optional): Maximum horizon limit in days.
        
    Returns:
        int: Planning horizon in minutes.
    """
    base_horizon = sum(task.duration for task in user_tasks)
    # TODO:
    # - fix const days
    # - when we get deadlines use they as horozon
    # - in future get user horizon
    return max(base_horizon * 3 + 1440, max_horizon_days * 1440)


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
    from data_structs import TimeBlock
    
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
            clamped_start = max(0, tb.start)
            if tb.end > 0:
                actual_blocks.append(TimeBlock(clamped_start, tb.end, daily=False))

    # Merge all overlapping intervals into one continuous list
    return [(block.start, block.end) for block in merge_time_blocks(actual_blocks)]


def create_model(user_tasks, time_blocks, max_horizon_days=14):
    model = cp_model.CpModel()
    tasks = {"var": [], "start": [], "end": []}

    # Data preparation and calculation of constraints
    horizon = calculate_horizon(user_tasks, max_horizon_days)
    blocked_time_intervals = generate_blocked_intervals(time_blocks, horizon)

    # Create variables for blocked periods (fixed intervals)
    time_blocks_vars = []
    for i, (start, end) in enumerate(blocked_time_intervals):
        fixed_interval = model.new_fixed_size_interval_var(start, end - start, f'blocked_{i+1}')
        time_blocks_vars.append(fixed_interval)

    # Create variables for each user task
    for i, task in enumerate(user_tasks):
        start_var = model.new_int_var(0, horizon, f'start_{i}')
        end_var = model.new_int_var(0, horizon, f'end_{i}')
        
        tasks["start"].append(start_var)
        tasks["end"].append(end_var)
        tasks["var"].append(model.new_interval_var(start_var, task.duration, end_var, f'task_{task.name}_interval'))

    # Tasks and blocked periods cannot overlap
    model.add_no_overlap(tasks["var"] + time_blocks_vars)

    return model, tasks
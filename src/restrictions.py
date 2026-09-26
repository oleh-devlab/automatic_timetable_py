import math
import itertools
import heapq
from dataclasses import dataclass, field
from ortools.sat.python import cp_model

from .utils import merge_time_blocks
from .chunking import calculate_chunks
from .data_structs import TimeBlock

# Ceiling on how far ahead a schedule may be planned when nothing else bounds it.
DEFAULT_MAX_HORIZON_DAYS = 365

# Stage 2 coefficients, per step and per step of work. GRAVITY_PULL is what a chunk gains
# by moving one step earlier; GRAVITY_GAP_PENALTY is what a task pays for one step of dead
# time inside itself. Only their ratio matters: the absolute scale only eats into the
# int64 headroom of the objective (docs/limits.md), so it is kept as small as the ratio allows.
GRAVITY_PULL = 100
GRAVITY_GAP_PENALTY = 1


def calculate_horizon(
    user_tasks, time_blocks, min_horizon_days=14, step_minutes=1, max_horizon_days=DEFAULT_MAX_HORIZON_DAYS
):
    """
    Calculates the safe planning horizon (maximum available time in minutes)

    The stretch of time the simulation explores is grown on demand: when the first-fit pass runs
    out of free windows before it has placed everything, the bound was too small, so it is
    doubled and the pass repeated. A deadline bounds where a task may go, it is never a reason to
    stretch the plan, so deadlines do not raise the returned horizon.
    """
    if min_horizon_days <= 0:
        raise ValueError(f"min_horizon_days must be greater than 0, got {min_horizon_days}")
    if max_horizon_days < min_horizon_days:
        raise ValueError(
            f"max_horizon_days ({max_horizon_days}) cannot be smaller than min_horizon_days ({min_horizon_days})"
        )

    steps_per_day = 1440 // step_minutes
    max_bound = max_horizon_days * steps_per_day

    # First guess at how far ahead free windows are needed; grown below whenever it binds.
    base_horizon = sum(task.duration_steps for task in user_tasks)
    max_deadline = max(
        (t.deadline_steps for t in user_tasks if getattr(t, "deadline_steps", None) is not None), default=0
    )
    initial_bound = max(base_horizon * 3 + steps_per_day, min_horizon_days * steps_per_day, max_deadline)

    task_by_id = {t.id: t for t in user_tasks if getattr(t, "id", None) is not None}
    in_degree = {t.id: 0 for t in user_tasks if getattr(t, "id", None) is not None}
    adj = {t.id: [] for t in user_tasks if getattr(t, "id", None) is not None}

    for t in user_tasks:
        if getattr(t, "depends_on", None):
            for dep_id in t.depends_on:
                if dep_id in adj:
                    adj[dep_id].append(t.id)
                    if t.id in in_degree:
                        in_degree[t.id] += 1

    counter = itertools.count()
    pq = []
    for t in user_tasks:
        if getattr(t, "id", None) is not None and in_degree[t.id] == 0:
            dl = t.deadline_steps if getattr(t, "deadline_steps", None) is not None else math.inf
            heapq.heappush(pq, (dl, next(counter), t.id))

    sorted_tasks = []
    while pq:
        _, _, task_id = heapq.heappop(pq)
        t = task_by_id[task_id]
        sorted_tasks.append(t)
        for child_id in adj[task_id]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                child = task_by_id[child_id]
                dl = child.deadline_steps if getattr(child, "deadline_steps", None) is not None else math.inf
                heapq.heappush(pq, (dl, next(counter), child_id))

    added = set(t.id for t in sorted_tasks)
    for t in user_tasks:
        if getattr(t, "id", None) is None or t.id not in added:
            sorted_tasks.append(t)

    def simulate(bound):
        """
        Greedily first-fits every task into the free windows below `bound`.

        Returns the finish time of the last non-routine task, and whether any chunk failed to be
        placed for want of a free window rather than for missing its own deadline -- the latter
        is a task that genuinely does not fit and that the model will drop as well, the former
        means `bound` itself was the limit.
        """
        blocked_intervals = generate_blocked_intervals(time_blocks, bound, step_minutes)
        free_windows = []
        curr = 0
        for start, end in blocked_intervals:
            if start > curr:
                free_windows.append((curr, start))
            curr = max(curr, end)
        if curr < bound:
            free_windows.append((curr, bound))

        release_times = {t.id: getattr(t, "start_steps", 0) for t in user_tasks if getattr(t, "id", None) is not None}
        simulated_horizon = 0
        ran_out_of_room = False

        for task in sorted_tasks:
            chunks = []
            if (
                getattr(task, "min_chunk_duration_steps", None) is not None
                and task.duration_steps > task.min_chunk_duration_steps
            ):
                max_chunks = math.ceil(task.duration_steps / task.min_chunk_duration_steps)
                remainder = task.duration_steps - (max_chunks - 1) * task.min_chunk_duration_steps
                for _ in range(max_chunks - 1):
                    chunks.append(task.min_chunk_duration_steps + task.break_duration_steps)
                chunks.append(remainder + task.break_duration_steps)
            else:
                chunks.append(task.duration_steps + task.break_duration_steps)

            t_curr = (
                release_times.get(task.id, getattr(task, "start_steps", 0))
                if getattr(task, "id", None) is not None
                else getattr(task, "start_steps", 0)
            )
            deadline = task.deadline_steps if getattr(task, "deadline_steps", None) is not None else math.inf

            for chunk_size in chunks:
                placed = False
                deadline_limited = False
                for i, (w_start, w_end) in enumerate(free_windows):
                    start_time = max(w_start, t_curr)
                    if w_end > start_time and (w_end - start_time) >= chunk_size:
                        if start_time + chunk_size <= deadline:
                            t_curr = start_time + chunk_size
                            # Split the window
                            new_windows = free_windows[:i]
                            if start_time > w_start:
                                new_windows.append((w_start, start_time))
                            if w_end > start_time + chunk_size:
                                new_windows.append((start_time + chunk_size, w_end))
                            new_windows.extend(free_windows[i + 1 :])
                            free_windows = new_windows
                            placed = True
                            break
                        deadline_limited = True
                if not placed:
                    if not deadline_limited:
                        ran_out_of_room = True
                    t_curr += chunk_size

            if not getattr(task, "is_routine", False):
                simulated_horizon = max(simulated_horizon, t_curr)
            if getattr(task, "id", None) is not None:
                for child_id in adj.get(task.id, []):
                    release_times[child_id] = max(release_times.get(child_id, 0), t_curr)

        return simulated_horizon, ran_out_of_room

    bound = initial_bound
    simulated_horizon, ran_out_of_room = simulate(bound)
    while ran_out_of_room and bound < max_bound:
        bound = min(bound * 2, max_bound)
        simulated_horizon, ran_out_of_room = simulate(bound)

    return min(max(simulated_horizon, min_horizon_days * steps_per_day), max_bound)


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
    # Deadlines farther away than this are indistinguishable from each other and from
    # having no deadline at all. Raising it widens the range of deadlines the model can
    # still tell apart, but weakens tier dominance, because it raises the maximum Low
    # Tier weight one High Tier task has to outweigh: at 365 days one High Tier task
    # outweighs 916 Low Tier ones, at 3650 it outweighs 522, at 36500 only 98.
    deadline_horizon_days = 3650  # 10 years

    # One day of deadline difference has to outweigh the whole priority span inside a
    # tier, so this must stay above max_priority - min_priority (10 for the documented
    # 0-10 range). That is what makes deadlines dominate priorities within a tier.
    deadline_step = 15
    priority_step = 1

    # Stage 1 maximizes a *sum* of weights, so the gap between the tiers is not about
    # beating a single Low Tier task - it is how many of them it takes to outweigh one
    # High Tier task. Hence the deliberately huge factor over the max in-tier weight.
    low_tier_base = 60000
    high_tier_base = low_tier_base * 1000

    # A missing deadline earns no bonus at all, which is also what a deadline sitting on
    # (or beyond) the horizon earns. Keep the two in sync: computing the missing case as
    # "a deadline exactly deadline_horizon_days away" would silently turn into maximum
    # urgency the moment the horizon and that substitute drift apart.
    if getattr(task, "deadline_steps", None) is None:
        days_inverted = 0
    else:
        steps_per_day = 1440 // step_minutes
        deadline_days = task.deadline_steps // steps_per_day
        days_inverted = max(0, deadline_horizon_days - deadline_days)

    weighted_priority = task.priority * priority_step

    if task.priority >= priority_threshold:
        return high_tier_base + (days_inverted * deadline_step) + weighted_priority
    else:
        return low_tier_base + (days_inverted * deadline_step) + weighted_priority


@dataclass
class StagedModel:
    """
    A built CP-SAT model together with what Stage 2 needs to take over from Stage 1.

    Stage 1's objective is already set on `model`. Stage 2's cannot be built yet: every
    present chunk is pulled towards the present in proportion to the work in it, and those
    weights are the chunk sizes Stage 1 settles on. So the objective is built by
    `apply_gravity_objective()`, from the Stage 1 solution, and needs no variables of its
    own — once presence is pinned, `horizon - start_var` is already a linear expression.
    """

    model: cp_model.CpModel
    horizon: int
    tasks: list = field(default_factory=list)

    def apply_gravity_objective(self, solver):
        """
        Pins every presence variable to the Stage 1 answer and switches to the Gravity objective.

        The two are one step, not two: the Gravity terms are plain `horizon - start_var`
        expressions, which are only meaningful while presence is pinned. With a chunk free to
        drop out, its start would be free too and its pull would be collected for nothing.

        Weighing each chunk's pull by its Stage 1 size is what keeps the pull per-chunk without
        a product of two variables. `size_var` stays free in Stage 2, so a weight can go stale,
        but a stale weight only skews a preference, never a constraint. Chunk sizes sum to
        `duration_steps` by construction, so a task's total pull does not depend on how many
        pieces the calendar forced it into.

        Pulling `task.start_var` alone (which aliases the first chunk) left every later chunk
        with no pull at all, and the gap penalty is far too weak to stand in for one: a
        priority 2 task could profitably wedge itself between the chunks of a priority 5 one.

        Args:
            solver: a CpSolver holding the Stage 1 solution.

        Returns:
            bool: whether there is anything for Stage 2 to optimise. False when every
            scheduled task has priority 0, which disables gravity (floating filler tasks).
        """
        terms = []

        for task in self.tasks:
            is_present = solver.value(task.presence_var)
            self.model.add(task.presence_var == is_present)
            present_chunks = []
            for chunk in task.chunks:
                chunk_present = solver.value(chunk["presence_var"])
                self.model.add(chunk["presence_var"] == chunk_present)
                if chunk_present:
                    present_chunks.append(chunk)

            gravity_multiplier = task.priority**3
            if not is_present or not gravity_multiplier:
                continue

            if present_chunks:
                pulls = [(chunk["start_var"], solver.value(chunk["size_var"])) for chunk in present_chunks]
            else:
                pulls = [(task.start_var, task.duration_steps)]

            # 1. Pull every piece of the task to the left, weighted by its mass (Bonus)
            for start_var, mass in pulls:
                terms.append((self.horizon - start_var) * (gravity_multiplier * GRAVITY_PULL * mass))

            # 2. Force chunks to stick together (Penalty for GAPS), scaled by the task's
            # whole mass so the ratio to the pull above does not drift with task length.
            task_gaps = task.end_var - task.start_var - task.duration_steps
            terms.append(task_gaps * (-gravity_multiplier * GRAVITY_GAP_PENALTY * task.duration_steps))

        if terms:
            self.model.maximize(sum(terms))
        return bool(terms)


def create_model(
    user_tasks,
    time_blocks,
    min_horizon_days=14,
    priority_threshold=5,
    horizon=None,
    step_minutes=1,
    max_horizon_days=DEFAULT_MAX_HORIZON_DAYS,
):
    model = cp_model.CpModel()

    # Data preparation and calculation of constraints
    if horizon is None:
        horizon = calculate_horizon(user_tasks, time_blocks, min_horizon_days, step_minutes, max_horizon_days)

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

        needs_chunking = (
            task.min_chunk_duration_steps is not None and task.duration_steps > task.min_chunk_duration_steps
        )

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
                model.add(ext_size == chunk["size_var"] + task.break_duration_steps).only_enforce_if(
                    chunk["presence_var"]
                )
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

                    model.add(chunk["size_var"] >= task.min_chunk_duration_steps).only_enforce_if(
                        next_chunk["presence_var"]
                    )

            model.add(sum(c["size_var"] for c in task.chunks) == task.duration_steps).only_enforce_if(task.presence_var)

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

    # Dependency constraints
    task_by_id = {task.id: task for task in user_tasks if getattr(task, "id", None) is not None}

    for task_b in user_tasks:
        if not getattr(task_b, "depends_on", None):
            continue

        for dep_id in task_b.depends_on:
            task_a = task_by_id.get(dep_id)
            if not task_a:
                continue

            # Rule 1: If B is scheduled, A MUST be scheduled
            model.add_implication(task_b.presence_var, task_a.presence_var)

            # Rule 2: If B is scheduled, B starts after A ends
            model.add(task_b.start_var >= task_a.end_var).only_enforce_if(task_b.presence_var)

    presence_terms = []  # Stage 1 (Packer): which tasks are worth scheduling

    for i, task in enumerate(user_tasks):
        fixed_weight = calculate_task_weight(task, priority_threshold, step_minutes)
        # Chunk sizes are capped at max_chunk_duration and have to add up to the whole
        # duration, so a chunked task cannot be placed in fewer than this many pieces no
        # matter how the calendar looks. Refunding them (only when the task is actually
        # scheduled, or the term would be a constant and cancel out) leaves the -1 below
        # charging for over-fragmentation alone, instead of charging every long task for
        # its length: an 8h task in 30-minute pieces used to arrive 16 points down, which
        # is more than a whole day of deadline is worth.
        unavoidable_chunks = 0
        if getattr(task, "chunks", None):
            unavoidable_chunks = math.ceil(task.duration_steps / task.max_chunk_duration_steps)
        presence_terms.append(task.presence_var * (fixed_weight + unavoidable_chunks))

        # 3. Force avoiding unnecessary splits (Micro-penalty in Stage 1)
        if getattr(task, "chunks", None):
            for c, chunk in enumerate(task.chunks):
                presence_terms.append(chunk["presence_var"] * -1)

        # Neither objective reads these two. They are what Stage 2 used to be built from, and
        # they stay only because Stage 1 was measured with them in place: dropping them proves
        # optimality faster but makes the Packer's answer more sensitive to the solver's seed.
        # Whether to keep them is an open Stage 1 question (docs/refactoring.md); Stage 2 no
        # longer depends on the answer.
        task_gravity = model.new_int_var(0, horizon, f"task_gravity_{i}")
        model.add(task_gravity == horizon - task.start_var).only_enforce_if(task.presence_var)
        model.add(task_gravity == 0).only_enforce_if(task.presence_var.negated())

        task_gaps = model.new_int_var(0, horizon, f"task_gaps_{i}")
        model.add(task_gaps == (task.end_var - task.start_var) - task.duration_steps).only_enforce_if(task.presence_var)
        model.add(task_gaps == 0).only_enforce_if(task.presence_var.negated())

    model.maximize(sum(presence_terms))

    return StagedModel(model=model, horizon=horizon, tasks=list(user_tasks))

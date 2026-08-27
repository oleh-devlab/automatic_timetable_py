from datetime import datetime, timedelta
import math
from .data_structs import TimeBlock


def merge_time_blocks(time_blocks):
    if not time_blocks:
        return []

    # Sort the time blocks by start time
    sorted_blocks = sorted(time_blocks, key=lambda block: block.start)
    merged_blocks = [sorted_blocks[0]]

    for current in sorted_blocks[1:]:
        last_merged = merged_blocks[-1]
        if current.start <= last_merged.end:  # Overlapping blocks
            last_merged.end = max(last_merged.end, current.end)  # Merge them
        else:
            merged_blocks.append(current)

    return merged_blocks


def minutes_to_time(minutes_from_now, now):
    """Convert minutes from `now` to a datetime object."""
    return now + timedelta(minutes=minutes_from_now)


def process_time_blocks(time_blocks, now, step_minutes=1):
    """Process TimeBlock objects, converting string times into minute offsets."""
    processed_blocks = []
    for b in time_blocks:
        # Ignore blocks that are already processed (ints)
        if isinstance(b.start, int) and isinstance(b.end, int):
            processed_blocks.append(b)
            continue

        # Weekly blocks are materialised by expand_time_blocks(), which needs the planning horizon
        if b.weekdays:
            continue

        daily = b.daily

        dt_start = b.start
        dt_end = b.end

        if daily:
            s = dt_start.hour * 60 + dt_start.minute
            e = dt_end.hour * 60 + dt_end.minute

            if e <= s:
                e += 24 * 60  # crosses midnight

            now_min = now.hour * 60 + now.minute

            start_min, end_min = 0, 0
            for k in [-1, 0, 1]:
                start_rel = s + k * 1440 - now_min
                end_rel = e + k * 1440 - now_min

                if end_rel > 0:
                    start_min = math.floor(start_rel / step_minutes)
                    end_min = math.ceil(end_rel / step_minutes)
                    break

            new_block = TimeBlock(start=start_min, end=end_min, daily=True, name=b.name, id=b.id)
            processed_blocks.append(new_block)

        else:
            start_min = (dt_start - now).total_seconds() / 60
            end_min = (dt_end - now).total_seconds() / 60

            if end_min > 0:
                new_block = TimeBlock(
                    start=math.floor(start_min / step_minutes),
                    end=math.ceil(end_min / step_minutes),
                    daily=False,
                    name=b.name,
                    id=b.id,
                )
                processed_blocks.append(new_block)

    return processed_blocks


def iter_active_dates(now, horizon_minutes, step_minutes=1, weekdays=None, start_day_offset=0):
    """Yield every calendar date inside the planning horizon that a recurring item applies to.

    This is the single place that turns "repeats weekly on these days" into concrete dates, shared
    by routine and time block expansion so both agree on what a weekday means.

    Args:
        now (datetime): Current time (start of the horizon).
        horizon_minutes (int): Planning horizon in steps.
        step_minutes (int): Minutes per step.
        weekdays (list[int] | None): Restrict to these weekdays (0=Monday). None means every day.
        start_day_offset (int): First day offset to consider. Use -1 for items whose occurrence may
            have started yesterday and still be running at `now` (blocks crossing midnight).

    Yields:
        date: Matching calendar dates, in chronological order.
    """
    steps_per_day = 1440 // step_minutes
    horizon_days = horizon_minutes // steps_per_day + 1

    for day_offset in range(start_day_offset, horizon_days + 1):
        current_date = (now + timedelta(days=day_offset)).date()
        if weekdays is not None and current_date.weekday() not in weekdays:
            continue
        yield current_date


def expand_time_blocks(time_blocks, now, horizon_minutes, step_minutes=1):
    """Materialise weekly-recurring TimeBlocks into concrete one-off occurrences.

    This is the block-side counterpart of fixed routines: all calendar work happens here, once, and
    everything downstream sees plain `daily=False` blocks expressed in step offsets.
    process_time_blocks() deliberately skips weekly blocks, because expanding them needs the
    planning horizon, which is only known later.

    Only the time-of-day part of `start`/`end` is used; the date part is a template. An occurrence is
    anchored on the weekday of its *start*, so a Friday 23:00-01:00 block belongs to Friday.

    Args:
        time_blocks (list[TimeBlock]): Original time blocks (datetime bounds, as loaded from JSON).
        now (datetime): Current time.
        horizon_minutes (int): Planning horizon in steps.
        step_minutes (int): Minutes per step.

    Returns:
        list[TimeBlock]: One non-daily block per occurrence, keeping the source name and id.
    """
    expanded_blocks = []

    for b in time_blocks:
        if not b.weekdays:
            continue

        start_min = b.start.hour * 60 + b.start.minute
        end_min = b.end.hour * 60 + b.end.minute
        if end_min <= start_min:
            end_min += 24 * 60  # crosses midnight
        duration = timedelta(minutes=end_min - start_min)
        start_time = b.start.time()

        for current_date in iter_active_dates(
            now, horizon_minutes, step_minutes, weekdays=b.weekdays, start_day_offset=-1
        ):
            start_dt = datetime.combine(current_date, start_time, tzinfo=now.tzinfo)
            end_dt = start_dt + duration

            start_steps = math.floor(((start_dt - now).total_seconds() / 60) / step_minutes)
            end_steps = math.ceil(((end_dt - now).total_seconds() / 60) / step_minutes)

            if end_steps > 0 and start_steps <= horizon_minutes:
                expanded_blocks.append(TimeBlock(start_steps, end_steps, daily=False, name=b.name, id=b.id))

    return expanded_blocks

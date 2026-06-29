from datetime import timedelta, datetime
from data_structs import TimeBlock

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
    """Convert minutes from `now` to a 'DD.MM.YYYY HH:MM' datetime string."""
    return (now + timedelta(minutes=minutes_from_now)).strftime('%d.%m.%Y %H:%M')


def parse_time_blocks(time_blocks_raw, now):
    """Parse time blocks containing full datetimes into TimeBlock objects."""
    time_blocks = []
    for b in time_blocks_raw:
        daily = b.get("daily", True)
        
        dt_start = datetime.strptime(b["start"], "%d.%m.%Y %H:%M")
        dt_end = datetime.strptime(b["end"], "%d.%m.%Y %H:%M")
        
        if daily:
            s = dt_start.hour * 60 + dt_start.minute
            e = dt_end.hour * 60 + dt_end.minute
            
            if e <= s:
                e += 24 * 60 # crosses midnight
                
            now_min = now.hour * 60 + now.minute
            
            # Find the first daily occurrence that hasn't completely passed yet
            start_min, end_min = 0, 0
            for k in [-1, 0, 1]:
                start_rel = s + k * 1440 - now_min
                end_rel = e + k * 1440 - now_min
                
                if end_rel > 0:
                    # Do NOT clamp start_rel to 0 here! We need the true offset for accurate cloning.
                    # Clamping will happen when generating variables for the solver.
                    start_min = int(start_rel)
                    end_min = int(end_rel)
                    break
                    
            time_blocks.append(TimeBlock(start_min, end_min, daily=True))
            
        else:
            # Absolute interval
            start_min = (dt_start - now).total_seconds() / 60
            end_min = (dt_end - now).total_seconds() / 60
            
            if end_min > 0:
                # Same here, do not clamp start_min to 0.
                time_blocks.append(TimeBlock(int(start_min), int(end_min), daily=False))
                
    return time_blocks

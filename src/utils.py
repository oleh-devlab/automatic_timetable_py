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
    """Convert minutes from `now` to a datetime object."""
    return now + timedelta(minutes=minutes_from_now)


def process_time_blocks(time_blocks, now):
    """Process TimeBlock objects, converting string times into minute offsets."""
    processed_blocks = []
    for b in time_blocks:
        daily = b.daily
        
        dt_start = datetime.strptime(b.start_str, "%d.%m.%Y %H:%M")
        dt_end = datetime.strptime(b.end_str, "%d.%m.%Y %H:%M")
        
        if daily:
            s = dt_start.hour * 60 + dt_start.minute
            e = dt_end.hour * 60 + dt_end.minute
            
            if e <= s:
                e += 24 * 60 # crosses midnight
                
            now_min = now.hour * 60 + now.minute
            
            start_min, end_min = 0, 0
            for k in [-1, 0, 1]:
                start_rel = s + k * 1440 - now_min
                end_rel = e + k * 1440 - now_min
                
                if end_rel > 0:
                    start_min = int(start_rel)
                    end_min = int(end_rel)
                    break
                    
            new_block = TimeBlock(b.start_str, b.end_str, daily=True)
            new_block.start = start_min
            new_block.end = end_min
            processed_blocks.append(new_block)
            
        else:
            start_min = (dt_start - now).total_seconds() / 60
            end_min = (dt_end - now).total_seconds() / 60
            
            if end_min > 0:
                new_block = TimeBlock(b.start_str, b.end_str, daily=False)
                new_block.start = int(start_min)
                new_block.end = int(end_min)
                processed_blocks.append(new_block)
                
    return processed_blocks

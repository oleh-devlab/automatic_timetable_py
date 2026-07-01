import json
from data_structs import Task, TimeBlock, Routine

def load_data(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    user_tasks = [
        Task(
            name=t["name"], 
            duration=t["duration"],
            deadline=t.get("deadline"),
            priority=t.get("priority", 0),
            min_chunk_duration=t.get("min_chunk_duration"),
            max_chunk_duration=t.get("max_chunk_duration"),
            break_duration=t.get("break_duration", 0)
        ) 
        for t in data.get("user_tasks", [])
    ]
    time_blocks_raw = [
        {"start": b["start"], "end": b["end"], "daily": b.get("daily", True)}
        for b in data.get("time_blocks", [])
    ]
    
    routines = [
        Routine(
            name=r["name"],
            routine_type=r["type"],
            repeat=r["repeat"],
            duration=r["duration"],
            time=r.get("time"),
            deadline_time=r.get("deadline_time"),
            weekdays=r.get("weekdays"),
            priority=r.get("priority", 0),
            break_duration=r.get("break_duration", 0)
        )
        for r in data.get("routines", [])
    ]
    
    return user_tasks, time_blocks_raw, routines
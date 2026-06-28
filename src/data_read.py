import json
from data_structs import Task, TimeBlock

def load_data(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    user_tasks = [
        Task(
            name=t["name"], 
            duration=t["duration"],
            min_chunk_duration=t.get("min_chunk_duration"),
            max_chunk_duration=t.get("max_chunk_duration"),
            break_duration=t.get("break_duration", 0)
        ) 
        for t in data["user_tasks"]
    ]
    time_blocks_raw = [
        {"start": b["start"], "end": b["end"], "daily": b.get("daily", True)}
        for b in data["time_blocks"]
    ]
    
    return user_tasks, time_blocks_raw
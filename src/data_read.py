import json
from data_structs import Task, TimeBlock

def load_data(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    user_tasks = [Task(t["name"], t["duration"]) for t in data["user_tasks"]]
    time_blocks_raw = [
        {"start": b["start"], "end": b["end"], "daily": b.get("daily", True)}
        for b in data["time_blocks"]
    ]
    
    return user_tasks, time_blocks_raw
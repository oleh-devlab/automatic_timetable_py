
class Task:
    def __init__(self, name, duration, deadline=None, priority=0, min_chunk_duration=None, max_chunk_duration=None, break_duration=0):
        self.name = name
        self.duration = duration
        self.deadline = deadline
        self.priority = priority
        self.min_chunk_duration = min_chunk_duration
        self.max_chunk_duration = max_chunk_duration
        self.break_duration = break_duration
        
        self.start_var = None
        self.end_var = None
        self.interval_var = None
        self.presence_var = None
        
        self.chunks = []

class TimeBlock:
    def __init__(self, start, end, daily=True):
        if start >= end:
            raise ValueError("Start time must be less than end time.")

        self.start = start
        self.end = end
        self.daily = daily
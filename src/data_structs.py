
class Task:
    def __init__(self, name, duration, deadline=None, priority=0, min_chunk_duration=None, max_chunk_duration=None, break_duration=0):
        if duration <= 0:
            raise ValueError(f"Task '{name}': duration must be greater than 0, got {duration}")
        if min_chunk_duration is not None and max_chunk_duration is not None:
            if min_chunk_duration > max_chunk_duration:
                raise ValueError(f"Task '{name}': min_chunk_duration ({min_chunk_duration}) cannot be greater than max_chunk_duration ({max_chunk_duration})")

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
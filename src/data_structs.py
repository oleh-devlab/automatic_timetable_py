
class Task:
    def __init__(self, name, duration, deadline=None, priority=0, chunk_duration=None):
        self.name = name
        self.duration = duration
        self.deadline = deadline
        self.priority = priority
        self.chunk_duration = chunk_duration
        self.start_var = None
        self.end_var = None
        self.interval_var = None
        self.presence_var = None

class TimeBlock:
    def __init__(self, start, end, daily=True):
        if start >= end:
            raise ValueError("Start time must be less than end time.")

        self.start = start
        self.end = end
        self.daily = daily
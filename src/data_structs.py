from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, time


@dataclass
class Task:
    name: str
    duration: int
    deadline: datetime | None = None
    priority: int = 0
    min_chunk_duration: int | None = None
    max_chunk_duration: int | None = None
    break_duration: int = 0

    start_min: int = field(init=False, default=0)

    start_var: Any | None = field(init=False, default=None)
    end_var: Any | None = field(init=False, default=None)
    interval_var: Any | None = field(init=False, default=None)
    presence_var: Any | None = field(init=False, default=None)

    chunks: list = field(init=False, default_factory=list)

    def __post_init__(self):
        if self.duration <= 0:
            raise ValueError(f"Task '{self.name}': duration must be greater than 0, got {self.duration}")
        if self.min_chunk_duration is not None and self.max_chunk_duration is not None:
            if self.min_chunk_duration > self.max_chunk_duration:
                raise ValueError(
                    f"Task '{self.name}': min_chunk_duration ({self.min_chunk_duration}) cannot be greater than max_chunk_duration ({self.max_chunk_duration})"
                )


@dataclass
class TimeBlock:
    start: int | datetime | None
    end: int | datetime | None
    daily: bool = True


@dataclass
class Routine:
    name: str
    type: str
    repeat: str
    duration: int
    time: time | datetime | None = None
    deadline_time: time | datetime | None = None
    weekdays: list[int] | None = None
    priority: int = 0
    break_duration: int = 0

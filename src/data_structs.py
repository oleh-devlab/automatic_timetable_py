from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, time, timedelta, date


@dataclass
class Task:
    name: str
    duration: timedelta
    id: int | str | None = None
    depends_on: list[int | str] = field(default_factory=list)
    deadline: datetime | None = None
    priority: int = 1
    min_chunk_duration: timedelta | None = None
    max_chunk_duration: timedelta | None = None
    break_duration: timedelta = field(default_factory=timedelta)

    start_steps: int = field(init=False, default=0)

    start_var: Any | None = field(init=False, default=None)
    end_var: Any | None = field(init=False, default=None)
    interval_var: Any | None = field(init=False, default=None)
    presence_var: Any | None = field(init=False, default=None)

    duration_steps: int = field(init=False, default=0)
    break_duration_steps: int = field(init=False, default=0)
    min_chunk_duration_steps: int | None = field(init=False, default=None)
    max_chunk_duration_steps: int | None = field(init=False, default=None)
    deadline_steps: int | None = field(init=False, default=None)

    chunks: list = field(init=False, default_factory=list)

    def __post_init__(self):
        if self.duration <= timedelta(0):
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
    duration: timedelta
    id: int | None = None
    depends_on: list[int] = field(default_factory=list)
    time: time | datetime | None = None
    deadline_time: time | datetime | None = None
    weekdays: list[int] | None = None
    priority: int = 1
    break_duration: timedelta = field(default_factory=timedelta)
    resume_after: date | None = None

    duration_steps: int = field(init=False, default=0)
    break_duration_steps: int = field(init=False, default=0)

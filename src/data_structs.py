from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    name: str
    duration: int
    deadline: str | None = None
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
    start: int | str | None
    end: int | str | None
    daily: bool = True

    start_str: str | None = field(init=False, default=None)
    end_str: str | None = field(init=False, default=None)

    def __post_init__(self):
        if isinstance(self.start, int) and isinstance(self.end, int):
            self.start_str = None
            self.end_str = None
        else:
            self.start_str = self.start
            self.end_str = self.end
            self.start = None
            self.end = None


@dataclass
class Routine:
    name: str
    type: str
    repeat: str
    duration: int
    time: str | None = None
    deadline_time: str | None = None
    weekdays: list[int] | None = None
    priority: int = 0
    break_duration: int = 0

import json
from datetime import datetime, timedelta, date
from .data_structs import Task, TimeBlock, Routine


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if dt_str:
        return datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
    return None


def _parse_time(t_str: str | None):
    if t_str:
        return datetime.strptime(t_str, "%H:%M").time()
    return None


def _parse_date(d_str: str | None) -> date | None:
    if d_str:
        return datetime.strptime(d_str, "%d.%m.%Y").date()
    return None


def load_data(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    user_tasks = [
        Task(
            name=t["name"],
            duration=timedelta(minutes=t["duration"]),
            id=t.get("id"),
            depends_on=t.get("depends_on", []),
            deadline=_parse_datetime(t.get("deadline")),
            priority=t.get("priority", 0),
            min_chunk_duration=(
                timedelta(minutes=t["min_chunk_duration"]) if t.get("min_chunk_duration") is not None else None
            ),
            max_chunk_duration=(
                timedelta(minutes=t["max_chunk_duration"]) if t.get("max_chunk_duration") is not None else None
            ),
            break_duration=timedelta(minutes=t.get("break_duration", 0)),
        )
        for t in data.get("user_tasks", [])
    ]
    time_blocks = [
        TimeBlock(start=_parse_datetime(b["start"]), end=_parse_datetime(b["end"]), daily=b.get("daily", True))
        for b in data.get("time_blocks", [])
    ]

    routines = [
        Routine(
            name=r["name"],
            type=r["type"],
            repeat=r["repeat"],
            duration=timedelta(minutes=r["duration"]),
            id=r.get("id"),
            depends_on=r.get("depends_on", []),
            time=_parse_time(r.get("time")),
            deadline_time=_parse_time(r.get("deadline_time")),
            weekdays=r.get("weekdays"),
            priority=r.get("priority", 0),
            break_duration=timedelta(minutes=r.get("break_duration", 0)),
            resume_after=_parse_date(r.get("resume_after")),
        )
        for r in data.get("routines", [])
    ]

    return user_tasks, time_blocks, routines

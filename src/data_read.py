import json
from datetime import datetime, timedelta, date
from .data_structs import Task, TimeBlock, Routine

_TOP_LEVEL_FIELDS = {"user_tasks", "time_blocks", "routines"}
_TASK_FIELDS = {
    "name",
    "duration",
    "id",
    "depends_on",
    "deadline",
    "priority",
    "min_chunk_duration",
    "max_chunk_duration",
    "break_duration",
}
_TIME_BLOCK_FIELDS = {"start", "end", "repeat", "weekdays", "name", "id"}
_ROUTINE_FIELDS = {
    "name",
    "type",
    "repeat",
    "duration",
    "id",
    "depends_on",
    "time",
    "deadline_time",
    "weekdays",
    "priority",
    "break_duration",
    "resume_after",
}

_TIME_BLOCK_REPEATS = {"once", "daily", "weekly"}
_ROUTINE_REPEATS = {"daily", "weekly"}


def _parse_datetime(dt_str: str | None) -> datetime | None:
    if dt_str:
        try:
            return datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        except ValueError:
            dt = datetime.fromisoformat(dt_str)
            return dt.replace(tzinfo=None)
    return None


def _parse_time(t_str: str | None):
    if t_str:
        return datetime.strptime(t_str, "%H:%M").time()
    return None


def _parse_date(d_str: str | None) -> date | None:
    if d_str:
        return datetime.strptime(d_str, "%d.%m.%Y").date()
    return None


def _check_fields(entry: dict, allowed: set[str], where: str):
    """Reject fields the parser does not understand instead of silently dropping them."""
    unknown = sorted(set(entry) - allowed)
    if unknown:
        raise ValueError(f"{where}: unknown field(s) {unknown}; allowed fields are {sorted(allowed)}")


def _required(entry: dict, field: str, where: str):
    if field not in entry:
        raise ValueError(f"{where}: missing required field '{field}'")
    return entry[field]


def _parse_repeat(entry: dict, allowed: set[str], where: str, default: str | None = None) -> str:
    """Validate a recurrence rule and its weekdays. Shared by time blocks and routines."""
    repeat = entry.get("repeat", default) if default is not None else _required(entry, "repeat", where)
    if repeat not in allowed:
        raise ValueError(f"{where}: 'repeat' must be one of {sorted(allowed)}, got {repeat!r}")

    weekdays = entry.get("weekdays")
    if repeat == "weekly" and not weekdays:
        raise ValueError(f"{where}: repeat 'weekly' needs a non-empty 'weekdays' list")
    if repeat != "weekly" and weekdays is not None:
        raise ValueError(f"{where}: 'weekdays' only applies to repeat 'weekly', not {repeat!r}")

    return repeat


def _read_task(t: dict, where: str) -> Task:
    _check_fields(t, _TASK_FIELDS, where)
    return Task(
        name=_required(t, "name", where),
        duration=timedelta(minutes=_required(t, "duration", where)),
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


def _read_time_block(b: dict, where: str) -> TimeBlock:
    _check_fields(b, _TIME_BLOCK_FIELDS, where)
    repeat = _parse_repeat(b, _TIME_BLOCK_REPEATS, where, default="daily")
    return TimeBlock(
        start=_parse_datetime(_required(b, "start", where)),
        end=_parse_datetime(_required(b, "end", where)),
        daily=(repeat == "daily"),
        name=b.get("name", ""),
        id=b.get("id"),
        weekdays=b.get("weekdays"),
    )


def _read_routine(r: dict, where: str) -> Routine:
    _check_fields(r, _ROUTINE_FIELDS, where)
    return Routine(
        name=_required(r, "name", where),
        type=_required(r, "type", where),
        repeat=_parse_repeat(r, _ROUTINE_REPEATS, where),
        duration=timedelta(minutes=_required(r, "duration", where)),
        id=r.get("id"),
        depends_on=r.get("depends_on", []),
        time=_parse_time(r.get("time")),
        deadline_time=_parse_time(r.get("deadline_time")),
        weekdays=r.get("weekdays"),
        priority=r.get("priority", 0),
        break_duration=timedelta(minutes=r.get("break_duration", 0)),
        resume_after=_parse_date(r.get("resume_after")),
    )


def load_data(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    _check_fields(data, _TOP_LEVEL_FIELDS, "data file")

    user_tasks = [_read_task(t, f"user_tasks[{i}]") for i, t in enumerate(data.get("user_tasks", []))]
    time_blocks = [_read_time_block(b, f"time_blocks[{i}]") for i, b in enumerate(data.get("time_blocks", []))]
    routines = [_read_routine(r, f"routines[{i}]") for i, r in enumerate(data.get("routines", []))]

    return user_tasks, time_blocks, routines

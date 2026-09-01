# Known defects

Actual bugs, as opposed to the design work in the other documents. Neither is fixed.

## 1. `min_chunk_duration` without `max_chunk_duration` crashes the solve

`data_read.load_data()` accepts a task carrying `min_chunk_duration` and no
`max_chunk_duration`. `Task.__post_init__` only compares the two when **both** are present,
so nothing rejects it. `calculate_chunks()` then returns 1 (it bails out when either bound is
`None`), but `create_model()` has already committed to the chunking branch and builds

```python
chunk["size_var"] = model.new_int_var(0, task.max_chunk_duration_steps, ...)
```

with `None` as the upper bound. The result is an opaque OR-Tools error naming a `Domain`
constructor, with nothing pointing at the task or the field:

```
TypeError: __init__(): incompatible constructor arguments.
  ...
Invoked with: 0, None
```

Reproduced from a plain JSON file — this is not an API-only path:

```json
{"user_tasks": [{"name": "study", "duration": 240, "priority": 2, "min_chunk_duration": 25}],
 "time_blocks": [], "routines": []}
```

`load_data()` returns the task with `min_chunk_duration=0:25:00, max_chunk_duration=None`,
and `Scheduler.solve()` raises.

**Fix.** Default `max_chunk_duration_steps` to `duration_steps` when it is absent. That both
removes the crash and is exactly the normalisation Step 1 of
[`refactoring.md`](refactoring.md#step-1--treat-an-unchunked-task-as-a-single-chunk) needs, so
the two should land together. The default must go on the `*_steps` field, not on the
user-facing `timedelta` — see that step for why.

Rejecting the combination in `data_read` with a named error would also be defensible, but
it forbids something the model can express perfectly well.

## 2. A failed Packer returns empty lists, `skipped_tasks` included

The loop that fills `skipped_tasks` and `skipped_routines` sits inside
`if result.is_successful:` (`scheduler.py:386`). When Stage 1 returns `UNKNOWN` or
`INFEASIBLE`, the caller gets a `ScheduleResult` where *every* list is empty — so "nothing
was scheduled and nothing was skipped" is indistinguishable from "there was nothing to do".

Tasks dropped **before** the model is built (deadline already past) are appended earlier and
do survive, which makes the shape inconsistent rather than uniformly empty.

Currently mitigated by documentation only: the root `README.md` and the `Scheduler.solve()`
docstring both say to read `packer_status` rather than infer failure from an empty schedule.

**Fix.** Populating `skipped_tasks` with every unscheduled task on a failed Packer is a
**behaviour change** for anyone already branching on the empty lists, so it needs an explicit
decision before it is made. Not done.

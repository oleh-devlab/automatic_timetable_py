# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -r requirements.txt        # ortools is the only runtime dependency

cp data.json.example data.json         # main.py reads ./data.json (gitignored); create it first
python main.py                         # example consumer of the library

python -m unittest discover            # full suite (run from repo root)
python -m unittest tests.test_solver                                   # one module
python -m unittest tests.test_solver.TestSolver.test_chunk_sizes_and_presence   # one test

ruff check .                           # CI gate (no config file — ruff defaults)
black .                                # line-length 120 (pyproject.toml)
```

CI (`.github/workflows/`) runs tests + `ruff check` on Python 3.14 for every push and PR. A third
workflow auto-formats with Black and opens a *separate* PR against the pushed branch if formatting
drifts, so run `black .` before pushing to avoid the noise.

## Architecture

`src/` is a library (public surface re-exported in `src/__init__.py`); `main.py` is just one consumer
that loads JSON and prints a schedule. Keep solver logic out of `main.py`.

### Pipeline

`data_read.load_data()` → `Scheduler.add_*()` → `Scheduler.solve()`, which internally:

1. Converts every `timedelta`/`datetime` on tasks and routines into **integer steps** (`*_steps`
   fields), relative to `now` rounded *up* to the next `step_minutes` boundary.
2. Drops tasks whose deadline is already past (`deadline_steps <= 0`) into `skipped_tasks` before the
   model is built.
3. `utils.process_time_blocks()` turns `TimeBlock.start/end` from datetimes into step offsets (daily
   blocks are collapsed to the first occurrence that has not yet ended; midnight-crossing handled).
   Weekly blocks (`weekdays` set) are *skipped* here — expanding them needs the horizon.
4. Computes the horizon in two passes: `routine_expansion.expand_routines()` and
   `utils.expand_time_blocks()` feed `restrictions.calculate_horizon()` (a greedy first-fit
   simulation over free windows, honouring dependency order and deadlines), then the result gets
   +1 day of slack, is snapped up to a whole day, and both are expanded *again* against that final
   horizon.
   `calculate_horizon()` grows the stretch it explores on demand — a pass that runs out of free
   windows before placing everything doubles the bound and retries, up to `max_horizon_days`
   (default `DEFAULT_MAX_HORIZON_DAYS`, 365). A deadline bounds where a task may go and never
   raises the horizon, so one distant deadline no longer inflates the whole model.
   **Whatever is expanded for that simulation must cover the whole explored stretch, not the first
   bound.** Daily blocks are templates and clone themselves to any bound the simulation reaches;
   pre-expanded occurrences are a finite list, and where that list ends the simulation sees free
   time and shortens the horizon. Both `expand_time_blocks()` and `expand_routines()` are therefore
   given `max_horizon_days * steps_per_day` for the simulation pass, and only the second, real
   expansion is bounded by the horizon that comes out of it.
5. `restrictions.create_model()` builds the CP-SAT model; the solver runs it twice (below).

### Everything is steps, not minutes

Inside the model, all quantities are integers in units of `step_minutes`. `step_minutes=1` (the
`Scheduler` default) means one step per minute; `main.py` uses 5 for speed. Only
`utils.minutes_to_time()` at the very end converts back to `datetime`. Anything new must be scaled
consistently — the model has no notion of minutes.

### Two-stage solve (Packer → Gravity)

`create_model()` sets the Stage 1 objective (`maximize(sum(presence_terms))`) and attaches the Stage 2
terms as an ad-hoc `model.time_bonus_terms` attribute on the `CpModel`. `Scheduler.solve()` then:

- **Stage 1 (Packer)** — decides *which* tasks fit, using `calculate_task_weight()`:
  `high_tier_base = 60_000_000` for `priority >= priority_threshold` vs `low_tier_base = 60_000` below
  it (one high-tier task outweighs any number of low-tier ones), plus a deadline bonus
  (`(3650 - deadline_days) * 15`, so nearer deadlines dominate priority *within* a tier), plus the raw
  priority as a tiebreak. Each present chunk also costs `-1`, discouraging over-fragmentation.
- **Stage 2 (Gravity)** — presence variables are pinned to the Stage 1 values, then the objective is
  replaced with the time bonuses: `priority**3 * 1000` per step pulled earlier, minus
  `priority**3 * 10` per step of gap between a task's first and last chunk. Priority 0 disables
  gravity entirely (floating filler tasks).

Solutions are read from a `safe_solution` dict cached after Stage 1, **not** from `solver.value()` at
the end — Stage 2 may time out or fail, in which case the Stage 1 placement survives. Preserve that
pattern when touching the solve loop.

### Model shape (`restrictions.create_model`)

Each task gets an optional interval plus a parallel *extended* interval covering
`duration + break_duration`. Two `add_no_overlap` constraints are posted: `strict_intervals` (tasks,
chunks and blocked time) and `extended_intervals` (tasks + their trailing breaks, excluding blocked
time — that is what lets a break merge into a following fixed block instead of demanding extra free
time).

Chunked tasks (`min_chunk_duration` set and shorter than the duration) get `calculate_chunks()`
optional intervals, each a plain `dict` (`start_var`/`end_var`/`size_var`/`presence_var`/
`interval_var`/`extended_interval_var`) appended to `task.chunks`. Chunks are forced to be used in
order (chunk *c* implies chunk *c-1*), sizes sum to the duration, and every non-final chunk must reach
`min_chunk_duration`. `task.start_var` aliases the first chunk's start and `task.end_var` is a max over
the present chunk ends.

### Solver state lives on the dataclasses

`Task` carries its own `*_var`, `*_steps` and `chunks` fields (declared `init=False`). `create_model()`
mutates the task objects it is given, so **a `Task` cannot be reused across two models** — build fresh
instances per solve. Routine-derived tasks additionally get attributes that are not on the dataclass
at all (`is_routine`, `routine_id`), set in `routine_expansion.py` and read back with `getattr(...)`
in the scheduler; follow that convention rather than widening `Task`.

### Routines

`expand_routines()` materialises recurring items per day across the horizon: `type="fixed"` becomes a
`TimeBlock` (plus a `routine_info` entry that `Scheduler.solve()` turns back into a `ScheduledRoutine`
without ever entering the model; an occurrence that started yesterday and is still running counts), `type="flexible"` becomes a synthetic `Task` with `start_steps`
pinned to the start of its day and a deadline of `deadline_time` (or 23:59). Flexible routines are
never chunked. IDs are namespaced `r_{routine_id}_{date}` so per-day `depends_on` links resolve within
the same day.

### Weekly time blocks

A `TimeBlock` with `weekdays` set (0=Monday, same convention as `Routine`; `repeat: "weekly"` in
JSON) recurs weekly, and is
handled exactly like a fixed routine: `utils.expand_time_blocks()` materialises one plain
`daily=False` block per matching calendar date, keeping `name`/`id`, so nothing downstream needs to
know about recurrence. Only the time-of-day part of `start`/`end` is used — the date is a template —
and an occurrence is anchored on the weekday of its *start*, so a Friday 23:00–01:00 block belongs to
Friday.

`utils.iter_active_dates()` is the one place that maps a recurrence rule onto calendar dates; both
`expand_routines()` and `expand_time_blocks()` go through it. Keep it that way — the weekday
semantics of blocks and routines should stay identical by construction. Both pass
`start_day_offset=-1`, so an occurrence that began yesterday and is still running at `now` survives
(the past-end filter, not the day range, is what drops finished ones).

### Two different time-block expansions

`generate_blocked_intervals()` (model input) clamps to 0 and merges overlaps; `_expand_timeblocks_for_export()`
(client output) keeps true past boundaries and per-block identity/name. Changing one usually means
changing the other. (Both only clone `daily` blocks — weekly ones arrive already expanded.)

The two are fed *different* lists. The model gets `combined_blocks` (user blocks + fixed-routine
blocks + weekly blocks); the export gets `export_blocks`, which drops the fixed-routine ones — those
reach the client as `ScheduledRoutine` built from `routine_info`, with exact calendar bounds and
`routine_id`, so exporting their TimeBlock twins too would render every fixed routine twice.
`scheduled_timeblocks` is only populated on a successful solve, like every other scheduled list.

## Conventions and gotchas

- Tests bypass `Scheduler` entirely: `tests/solver_test_utils.BaseSolverTest._solve()` computes the
  `*_steps` fields itself, calls `create_model()`, runs both stages and asserts global invariants
  (no overlap, chunk sums, breaks, deadlines). **Any new derived field must be populated in both
  `Scheduler.solve()` and the test helper**, or tests will diverge from production behaviour.
- Subclasses set a class-level `step_minutes` (see the bottom of `tests/test_solver.py`) to re-run the
  same assertions at coarser granularity; `BaseSolverTest` defaults it to 1.
- `TimeBlock` fields are dual-typed (`datetime` before processing, `int` steps after);
  `process_time_blocks()` passes through blocks whose bounds are already ints, and the test helper
  marks scaled blocks with `_scaled`.
- Datetime strings are `"%d.%m.%Y %H:%M"` (ISO 8601 is accepted as a fallback in `_parse_datetime`);
  times are `"%H:%M"`, dates `"%d.%m.%Y"`.
- `data_read.load_data()` defaults `priority` to `0`, while the `Task`/`Routine` dataclasses default to
  `1` — a JSON task with no priority becomes a gravity-free floating task, not a priority-1 one.
- The JSON grammar says `repeat`, the dataclasses say `daily`. A time block takes
  `repeat: "once" | "daily" | "weekly"` (default `"daily"`), which `load_data()` normalises into the
  `daily` bool plus `weekdays`; routines keep their own `repeat: "daily" | "weekly"`. `weekdays` is
  required for `"weekly"` and rejected for anything else, in both. Keep the enum on the input side
  only — see "Weekly time blocks" for why the step layer wants a bool.
- The parser is strict: unknown fields (at the top level or inside any task, block or routine) and
  missing required ones raise `ValueError` naming the element, e.g. `time_blocks[0]`. Adding a field
  to a dataclass means adding it to the matching `_*_FIELDS` set in `data_read.py`, or files using it
  will be rejected.

# Restructuring plan

`create_model()` mixes variable creation, three unrelated constraint families and interface
plumbing in one loop; `Scheduler.solve()` carries four separate responsibilities. This is
the plan to unpick that, ordered so each step is independently shippable and the risky ones
come last.

## Where things live today

| stage | location | note |
|---|---|---|
| `timedelta` → steps |  `scheduler.py:213-231` | **duplicated** in `tests/solver_test_utils.py:22-31` |
| expired-task filtering | `scheduler.py:234-241` and `269-272` | two separate blocks, different code |
| routine / block expansion | `routine_expansion.py`, `utils.expand_time_blocks()` | called **twice** — simulation pass, then real pass |
| horizon | `restrictions.calculate_horizon():14-160` | carries its **own** model of chunking |
| model construction | `restrictions.create_model():243-463` | the tangle |
| two-stage solve, `safe_solution` | `scheduler.py:316-372` | |
| steps → datetime, result assembly | `scheduler.py:374-443` | longest block in the file |

Inside `create_model()`, three passes are **already** in the shape we want — deadlines
(`389-397`), dependencies (`400-416`) and the objectives (`418-460`) are each a separate
loop over `user_tasks`. The tangle is one loop, `270-381`:

```
270-273   domain bound from the deadline
275-277   decide whether to chunk
279-360   chunked branch
            288-318  variable creation: start/end/size/presence per chunk,
                     plus ext_size/ext_end and two interval vars,
                     plus registration into strict_/extended_intervals
            322-341  second pass: size↔presence, chunk→task, ordering,
                     inter-chunk break, min_chunk for non-final chunks
            343      sum(size) == duration
            345-346  task absent → all chunks absent
            349      task.start_var aliases chunks[0]["start_var"]
            351-358  N extra actual_end vars + add_max_equality for end_var
361-381   unchunked branch: the same thing again, flat
```

Four different kinds of thing in one loop: variable creation, structural chunk constraints,
break modelling (**written twice**, once per branch), and interface plumbing
(`start_var`/`end_var` aliases that exist for the rest of the codebase, not for the model).

## Step 1 — treat an unchunked task as a single chunk

Give a task with no chunking one chunk with `max_chunk_duration_steps = duration_steps`.

**Removes:** the whole `else` branch (`361-381`), so break modelling stops being written
twice; the `if task.chunks:` branch in the deadline pass (`390-397`); both
`getattr(task, "chunks", None)` guards in the objective (`434`, `439`).

**Already prepared for:** `calculate_chunks()` returns 1 for the unchunked case.

**Neutral in the objective, but only because of `2c78e47`.** Under unification every task
pays `-1` for its single chunk and is refunded `ceil(duration/duration) = 1`. Exactly zero,
matching today's no-chunks-no-penalty. Before the refund commit this would have silently
docked every unchunked task by exactly one priority step.

**Cost — measured, and half of it is avoidable:**

- swapping the fixed-size interval for a variable-size one plus `size == duration` is
  **free**; presolve folds it back (30/90/120-day runs identical to baseline);
- building `end_var` through `actual_end` + `add_max_equality` is **not** free. Three runs at
  a 120-day horizon with 726 unchunked routine tasks: baseline 11.0 / 10.9 / 10.8 s versus
  12.3 / 12.3 / 12.0 s — a stable ~12%;
- **with the single-chunk shortcut it is free again**: 11.2 / 10.5 / 10.8 s.

The shortcut, symmetric with what `start_var` already does:

```python
task.start_var = task.chunks[0]["start_var"]   # already there
task.end_var   = task.chunks[0]["end_var"]     # when there is exactly one chunk
```

Safe because the `actual_end` machinery exists only to skip *absent* chunks, whose `end_var`
is meaningless; with one chunk, chunk presence is identical to task presence and there is
nothing to skip.

**Where the default must not go.** Not into `min_chunk_duration` / `max_chunk_duration` —
those are user-facing fields that `data_read` reads, and overwriting them erases the
difference between "not chunkable" and "chunkable into exactly one piece". The default
belongs on `max_chunk_duration_steps`, which is `init=False` and already solver-internal.

**Which forces Step 2**, because `*_steps` are filled in two places.

## Step 2 — one shared step-normalisation

`Scheduler.solve():213-232` and `BaseSolverTest._solve():22-31` both compute `*_steps`
independently. `CLAUDE.md` states the rule ("any new derived field must be populated in
both"); a shared function removes the rule instead of restating it.

Third client: the horizon simulator (`restrictions.py:102-113`) splits a task into
**minimum-size** chunks, i.e. the maximum count — the exact opposite of what `create_model()`
now pulls towards. Pessimism is safe for a horizon estimate, so this is not a bug, but it is
a second independent answer to "how does a task split", and it does not call
`calculate_chunks()` even though that function is right there.

Also fixes a real crash — see [`known-defects.md`](known-defects.md#1).

## Step 3 — split the two objectives

Today one loop (`424-455`) builds both objectives and Stage 2's terms leave through
`model.time_bonus_terms`, an attribute stuck onto the `CpModel`. That is the only channel
between `create_model()` and `Scheduler.solve()`, and it is invisible.

Two functions over the same context make the stage boundary — the central design decision
of this solver — visible in the code rather than in a comment. This is the step that pays
back most per line touched, and it does not go near variable creation.

## Step 4 — phase structure

The proposed "each constraint is a function taking all data and returning modified data"
does not fit CP-SAT: `model.add(...)` mutates in place and returns a constraint handle.
There is nothing to thread through, because the variables already live **on the `Task`
objects** (`task.start_var`, `task.chunks`) — the data is already shared mutable state.
That is also why `CLAUDE.md` warns a `Task` cannot be reused across two models.

Constraints *are* order-independent, so a list of them is viable — with two exceptions:

- variables must exist before any constraint referencing them;
- `add_no_overlap` must come after `strict_intervals` / `extended_intervals` are complete.
  It is a finalisation step, not a peer.

So the realistic shape is phases, not one loop:

```
ctx = prepare(...)                                  # horizon, blocked intervals, registries
for build in VARIABLE_BUILDERS: build(model, ctx)
for post  in CONSTRAINTS:       post(model, ctx)    # order-free
finalize(model, ctx)                                # both add_no_overlap
stage1, stage2 = build_objectives(model, ctx)
```

`ctx` would name what are currently locals of `create_model()`: `horizon`,
`strict_intervals`, `extended_intervals`, `blocked_time_intervals`, `task_by_id`.

## Step 5 — `Scheduler.solve()`

278 lines doing four things: unit preparation, the two-pass horizon computation, solver
orchestration, and mapping results back to calendar types. The result assembly
(`374-443`) is the largest and the most mechanical, and is the natural first extraction.

## Traps

Three quiet ones. Each has already caused a failure or is one edit away from it.

1. **`task.start_var = task.chunks[0]["start_var"]` (`349`) is an alias, not a copy.** They
   are the *same* CP-SAT variable. A loop that walks both tasks and chunks feeds one variable
   twice; with solution hints that produces a bare `MODEL_INVALID` whose message names only a
   variable index.
2. **`task.end_var` for a chunked task is a max over `actual_end`, not
   `chunks[-1]["end_var"]`.** Absent chunks have an `end_var` inside its domain but no
   meaning; `actual_end` zeroes them first. Simplifying this the "obvious" way makes `end_var`
   pick up garbage.
3. **Stage 2 writes into `safe_solution` only on `OPTIMAL`/`FEASIBLE` (`scheduler.py:361`).**
   That is what makes a failed or overflowing Stage 2 degrade into "valid schedule, not
   cosmetically sorted" instead of an error. Any tidying of that loop must keep it.

Plus the standing rule: `main.py` is a consumer example, not production, and solver logic
must stay out of it.

## Suggested order

1. Step 3 (split the objectives) — smallest, highest payoff, no variable creation touched.
2. Step 2 (shared normalisation) — also fixes a real crash.
3. Step 1 (single-chunk unification) — free with the `end_var` shortcut, shortens the big
   loop by roughly a third.
4. Step 5 (result assembly out of `solve()`).
5. Step 4 (full phase structure) — only worth it once 1–3 have already removed the
   duplication it would otherwise enshrine.

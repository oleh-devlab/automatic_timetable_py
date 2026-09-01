# Real operating limits

Where the model stops behaving the way the documentation claims, what it takes to get
there, and how each figure was established. Ordered by how close each one is to ordinary
use.

Summary:

| limit | breaks when | signal when it breaks | reachable in practice |
|---|---|---|---|
| tier dominance | >522 low-tier tasks contend for the *same* time one high-tier task needs | none — a plain `OPTIMAL` | no, see below |
| in-tier deadline dominance | priority span inside one tier ≥ 15 | none | only by exceeding the documented 0–10 range |
| `low_tier_base` floor | a task's chunk penalty reaches its whole weight | task silently dropped | no (would need ~60 000 excess chunks) |
| deadline horizon | deadline more than 10 years out | none, and correctly so | no |
| Stage 2 coefficients | `priority**3 * 1000 * horizon * n_tasks` exceeds int64 | `MODEL_INVALID` on Stage 2; **the schedule survives** | no (needs priority ≈ 1000) |
| Packer returns `UNKNOWN` | oversubscribed input with `num_search_workers=1` | `packer_status == "UNKNOWN"`, every list empty | yes — use 2+ workers |

## 1. Tier dominance

**The claim under test.** One High Tier task outweighs any number of Low Tier tasks.

**The arithmetic.** Stage 1 maximises a *sum*, so the guarantee is finite. The smallest
High Tier weight is `60_000_000 + priority_threshold`; the largest Low Tier weight is
`60_000 + 3650*15 + 4 = 114_760`. The ratio is **522**.

**The framing that was wrong.** The first version of this note said the limit was reached
at "6 daily routines × 87 days", because flexible routines are the worst possible Low Tier
task by construction — they get a same-day deadline (`deadline_time`, or 23:59), so
`deadline_days == 0` and every one of them carries the maximum deadline bonus.

Running it showed that reasoning is wrong:

```
 30d, 6 routines | packer OPTIMAL | 186 low-tier tasks | HIGH_TIER kept |  5.7s
 90d, 6 routines | packer OPTIMAL | 546 low-tier tasks | HIGH_TIER kept |  8.0s
120d, 6 routines | packer OPTIMAL | 726 low-tier tasks | HIGH_TIER kept | 11.0s
```

546 and 726 are both well past 522 and nothing breaks. **Stage 1 does not trade globally.**
A flexible routine is pinned to its own day (`start_steps` at the day's start, deadline at
its end), so dropping the High Tier task frees time only on the days that task occupied,
and can only admit the handful of routines overlapping it. The other 540 never enter the
trade.

**What the limit actually is.** The displaced Low Tier tasks must all fit in the time the
one High Tier task occupies. That makes it a ratio of durations, not a count of tasks:

```
duration(high tier task)  ≥  522 × duration(low tier task)
```

Confirmed by holding the contended window at 600 minutes and varying only the size of the
Low Tier tasks that compete for it:

```
low task =  5 min -> 120 of them fit | HIGH_TIER kept
low task =  2 min -> 300 of them fit | HIGH_TIER kept
low task =  1 min -> 600 of them fit | HIGH_TIER DROPPED
```

The transition sits exactly where the count crosses 522.

**Verdict: not reachable.** At `step_minutes=5` the shortest possible task is 5 minutes, so
the High Tier task that loses would have to occupy 43.5 contiguous hours. A three-hour High
Tier task would need to be outvoted by 522 tasks of 20 seconds each, which is below the grid.

The fix (deriving the base from the input instead of fixing it) is in
[`magic-numbers.md`](magic-numbers.md#high_tier_base--low_tier_base--1000); it is worth doing
for the coupling it removes, not for this limit.

## 2. Deadline dominance inside a tier

**The claim under test.** Within one tier, a deadline nearer by a day beats any priority
difference.

**The budget.** One day of deadline is worth `deadline_step = 15`. Everything on the unit
scale competes for that budget — and priority is not the only thing there. Stage 1 also
subtracts 1 per present chunk.

**Priority's share is smaller than it looks.** The tier split halves the span. At
`priority_threshold = 5` and the documented 0–10 range, Low Tier is 0–4 (span 4) and High
Tier is 5–10 (span 5). Not 10.

**The chunk penalty's share used to be the problem.** Before the refund (`2c78e47`), the
penalty grew with the task's *length*: an 8-hour task in 30-minute pieces can never use
fewer than 16, so it entered the objective 16 points down — more than a whole day of
deadline. Demonstrated on the real solver, one 8-hour slot and two 8-hour tasks in the same
tier, differing only in that the nearer-deadline one was chunked; Stage 1 dropped it in
favour of the later deadline. That case is now locked by
`test_chunking_does_not_cost_a_task_its_deadline`.

After the refund, only fragmentation the calendar *forced* is charged. Measured on a
deliberately shredded calendar (sleep plus six blocks a day — lectures, commute, meals),
ten 3-hour tasks with 25/50-minute chunking:

```
study0..study9: chunks 4, unavoidable 4, excess 0
```

Zero across the board.

**Verdict: livable, with one exposure.** The remaining consumer is the in-tier priority
span, and nothing in the code bounds it. Priorities 5 and 21 in the same tier give a span of
16 > 15 and deadlines stop dominating. The root `README.md` recommends 0–10; that
recommendation is load-bearing, not stylistic.

## 3. The `low_tier_base` floor

`low_tier_base` has a second job that is nowhere stated: it must exceed the largest chunk
penalty a task can pay, or scheduling a task becomes worth less than not scheduling it.

Measured with a priority-0 task with no deadline (so its weight is exactly the base) on a
calendar sliced into 40-minute windows, where a 50-minute maximum chunk forces excess:

```
low_tier_base = 60000:  weight 60000  objective 59999  SCHEDULED
low_tier_base = 0    :  weight 0      objective 0      DROPPED (with plenty of room free)
```

**Verdict: not reachable.** Breaking it needs ~60 000 excess chunks in one task. But the
constraint is real and must be respected if the tier bases are ever re-derived.

## 4. Deadline horizon

Deadlines further out than `deadline_horizon_days = 3650` are indistinguishable from each
other and from having no deadline at all. Intentional, and locked by
`test_very_distant_deadline` and `test_no_deadline_matches_an_arbitrarily_distant_deadline`.

**Verdict: not reachable, and correct as designed.**

## 5. Stage 2 coefficient growth

Stage 2 weights each task by `priority**3`, then by 1000 (pull left) and 10 (close gaps).
The objective sum grows as `priority**3 * 1000 * horizon_steps * n_tasks`, and CP-SAT
requires it to fit in int64.

Measured, 20 tasks, 365-day horizon:

```
prio    10, step 1: coeff 1e6   worst sum 1.05e13   stage1 OPTIMAL  stage2 OPTIMAL
prio   100, step 1: coeff 1e9   worst sum 1.05e16   stage1 OPTIMAL  stage2 OPTIMAL
prio  1000, step 1: coeff 1e12  worst sum 1.05e19   stage1 OPTIMAL  stage2 MODEL_INVALID
prio  1000, step 5: coeff 1e12  worst sum 2.10e18   stage1 OPTIMAL  stage2 OPTIMAL
```

**Stage 1 stays `OPTIMAL` in every case, and the schedule survives.** That is not luck:
`safe_solution` is filled from Stage 1 and Stage 2's values are copied back only on
`OPTIMAL`/`FEASIBLE` (`scheduler.py:361`). An overflowing Stage 2 therefore degrades to
"a valid schedule that was not cosmetically sorted", not to a failure.

This is what the root `README.md` means by "exceeding priority 10 is mathematically safe
due to the underlying Two-Stage architecture". The sentence is true, but the reason is
worth stating plainly: it is safe because a Stage 2 failure is *survivable by design*, not
because Stage 2 cannot fail.

`step_minutes=5` moves the threshold up fivefold, since the horizon in steps is five times
smaller.

**Verdict: livable.** Under a 0–10 range the largest multiplier is 1000 and the margin is
eight orders of magnitude.

## 6. Packer `UNKNOWN` with a single worker

Documented in the root `README.md` under *Solver Settings*, with its measurement table.
Repeated here only because it is the one limit on this page that is genuinely easy to hit:
with `num_search_workers=1` an oversubscribed input can return `UNKNOWN` even though
"schedule nothing" is always feasible, and a longer timeout does not help while a second
worker does.

## 7. Horizon ceiling

`DEFAULT_MAX_HORIZON_DAYS = 365`. `calculate_horizon()` grows what it explores on demand up
to this ceiling and rejects a `min_horizon_days` above it. This also caps how large the
Stage 1 objective and the Stage 2 coefficients can get, which is why the magnitudes in §5
have the headroom they do.

# Hand-picked constants

Every literal in `calculate_task_weight()` and in the two objectives: what it does, what
actually constrains it, and what replacing it would cost. Ordered by how worthwhile the
replacement is.

Current values, all in `src/restrictions.py`:

```python
deadline_horizon_days = 3650          # calculate_task_weight()
deadline_step         = 15
priority_step         = 1
low_tier_base         = 60_000
high_tier_base        = low_tier_base * 1000

gravity_multiplier    = task.priority**3   # create_model(), Stage 2 terms
task_gravity * (gravity_multiplier * 1000)
task_gaps    * (-gravity_multiplier * 10)
```

## `high_tier_base = low_tier_base * 1000` — worth deriving

**What it is.** The gap between the tiers. Because Stage 1 maximises a *sum*, the gap is not
"is one High Tier task bigger than one Low Tier task" — it is *how many* Low Tier tasks it
takes to outweigh one.

**The problem.** That count is 522, and it is specified nowhere. It falls out of four other
constants (`1000`, `60_000`, `3650`, `15`). Change any one of them and 522 moves silently;
the only place it is written down is prose.

**The cheap fix — name the count and derive the base:**

```python
max_low_tier_weight = low_tier_base + deadline_horizon_days * deadline_step + max_priority
high_tier_base      = min_high_tier_tasks_beaten * max_low_tier_weight
```

Trialled with `min_high_tier_tasks_beaten = 522`: gives `59_904_720` instead of
`60_000_000`, all 195 tests pass. Safe because the base **cancels** out of every comparison
that is not high-vs-low: High vs High it cancels, Low vs Low it does not appear. The only
thing it influences is the count it is meant to control.

**The better fix — derive it from the actual input.** The requirement is really "one High
Tier task outweighs *all* Low Tier tasks", with no arbitrary N at all:

```python
low_tier_total = sum(calculate_task_weight(t, ...) for t in user_tasks
                     if t.priority < priority_threshold)
max_chunk_penalty = sum(len(t.chunks) for t in user_tasks)
high_tier_base = low_tier_total + max_chunk_penalty + 1
```

Measured:

- holds where the fixed base fails — 600 and 2000 competing Low Tier tasks, High Tier kept
  in both, whereas the fixed base drops it at 600;
- **no measurable cost** — identical status, schedule and wall time at horizons of 7, 30,
  120 and 365 days;
- magnitudes stay small: 21 301 837 at a 30-day horizon (*below* the current fixed base),
  245 981 647 at 365 days, worst-case objective 3.0e9, int64 headroom ~3e9×. The 365-day
  `max_horizon_days` ceiling caps growth anyway.

Why `+ max_chunk_penalty`: the High Tier task can itself be docked for over-fragmentation
while the Low Tier tasks sit at their maximum weight. `sum(len(t.chunks))` is a loose but
free upper bound; `len(chunks) - unavoidable` would be tighter.

**Knock-on effect, and the reason to do this one first:** once dominance is guaranteed by
construction, `deadline_horizon_days` and `deadline_step` stop paying for it. The whole
trade-off table below disappears, which is exactly what makes `deadline_step` intractable
today.

**Costs to accept:**

- `calculate_task_weight()` needs the base passed in. It is unit-tested directly with a
  single task, so keep a default parameter and existing calls stay valid.
- A High Tier task's weight becomes input-dependent. No *ordering* changes — see the
  cancellation argument above — but a weight is no longer a stable number across runs, which
  matters for logs and debugging.
- With no Low Tier tasks at all the base is 1. Harmless inside a model, ugly in a log; a
  floor may be wanted.

## `low_tier_base = 60_000` — fix together with the above

Two jobs, only one of them obvious:

1. it separates the tiers (together with `high_tier_base`);
2. **it must exceed the largest chunk penalty a task can pay**, or a task becomes worth
   less scheduled than skipped. Measured — see [`limits.md`](limits.md#3-the-low_tier_base-floor).

Job 2 is nowhere in the code or the comments. If the bases are re-derived, it has to be
carried along as an explicit lower bound.

## `deadline_horizon_days = 3650` — partly fixed already

**Fixed in this branch** (`9453f63`): the literal used to appear twice in one expression,
serving as both the clamp ceiling and the stand-in value substituted for a missing deadline.
Those two only agree while the numbers are identical, and the coupling is *asymmetric* —
widening the clamp alone turns a task with no deadline from the least urgent in its tier
into the **most** urgent. It is now one named variable with the missing case handled in its
own branch, so the drift is unrepresentable, and
`test_no_deadline_matches_an_arbitrarily_distant_deadline` pins the identity.

**What remains.** It still silently sets the tier-dominance count, because it inflates the
maximum Low Tier weight:

| `deadline_horizon_days` | reach | max Low Tier weight | Low Tier tasks per High Tier one |
|---|---|---|---|
| 365 | 1 year | 65 485 | 916 |
| 1825 | 5 years | 87 385 | 686 |
| **3650** | **10 years** | **114 760** | **522** |
| 7300 | 20 years | 169 510 | 353 |
| 36500 | 100 years | 607 510 | 98 |

Deriving `high_tier_base` from the input removes this coupling entirely.

Note it is **free** for ordering between two tasks that both have deadlines — it is a common
offset and cancels: `w(A) - w(B) = 15 * (days_B - days_A)`.

## `deadline_step = 15` — hardest, leave for last

**What it is.** Not a weight but the **base of a positional system**. `days_inverted * 15 +
priority` is a two-digit number in base 15: deadline is the high digit, priority the low one.
While everything below a day stays under 15, comparison is lexicographic — deadline first,
priority only as a tiebreak. That is Key Rule 2 in the root `README.md`, implemented as
"pick a base larger than the low digit's range".

**Why it cannot simply be dropped.** At `deadline_step = 1` the digits merge into one sum and
start trading: priority 0 due in 5 days scores 63 645, priority 4 due in 8 days scores
63 646 — the later deadline wins. Inversion whenever
`Δdays * deadline_step < Δpriority`.

**Nothing pins it.** All 195 tests pass with `deadline_step = 1`. The existing rule-2 tests
use deadline gaps of 29 days, where the margin is so large the base is irrelevant.

**Why it is hard to derive.** An honest value needs upper bounds on two quantities the code
does not bound: the in-tier priority span, and forced over-fragmentation. Both are
computable from the task set — but then a task's weight would depend on the *other* tasks in
the file, so adding an unrelated task would reshuffle priorities. That is worse than a
literal. A fixed generous value (say 1024) pays for itself in tier dominance — unless
`high_tier_base` is derived first, at which point the payment disappears.

**Current exposure** is measured in [`limits.md`](limits.md#2-deadline-dominance-inside-a-tier):
the priority span consumes 4–5 of the 15, the chunk penalty consumes 0 after the refund.

## Stage 2: `priority**3`, `1000`, `10` — name them, do not derive them

Safest of the lot to experiment with: Stage 2 runs with presence pinned, so a mistake can
only produce an ugly ordering, never a dropped task.

Two things worth writing down rather than changing:

- **`1000 : 10` is a 100:1 ratio** meaning "one step earlier is worth 100 steps of gap".
  Pure taste; there is no value to derive it from.
- **`priority**3` cancels out of the within-task trade-off.** Both terms are multiplied by
  it, so for a single task the choice between starting earlier and opening a gap does not
  depend on priority at all. Priority only decides competition *between* tasks. This is not
  obvious from reading the code and is worth a comment.

Growth of the coefficients is bounded — see [`limits.md`](limits.md#5-stage-2-coefficient-growth).

## Priority defaults are inconsistent (separate from the above)

`data_read.load_data()` defaults `priority` to `0`, while the `Task`/`Routine` dataclasses
default to `1`. A JSON task with no priority becomes a gravity-free floating task, not a
priority-1 one. Already noted in `CLAUDE.md`; repeated here because it interacts with every
threshold discussion above.

## If the priority range is narrowed

Capping priorities at 4–5 makes the in-tier span trivially safe and the Stage 2 cube
harmless (`5**3 = 125`). But `priority_threshold` defaults to **5** and the split is
`priority >= threshold`, so a maximum priority of 4 leaves **no** High Tier tasks at all and
the two-tier system collapses into a plain weighted knapsack. Narrowing the range means
moving the threshold with it — e.g. priorities 0–4 with `priority_threshold = 3`, giving
Low 0–2 and High 3–4.

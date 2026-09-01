# Design notes

Working notes on the solver's numbers, its real operating limits, and the restructuring
that has not been done yet. None of this is user documentation — that lives in the root
`README.md`. Nothing here describes behaviour that is not in the code today unless it says
so explicitly.

| document | what it holds |
|---|---|
| [`limits.md`](limits.md) | where the model actually stops working, and how each limit was established |
| [`magic-numbers.md`](magic-numbers.md) | every hand-picked constant: what constrains it, what it costs, how to derive it |
| [`refactoring.md`](refactoring.md) | the restructuring plan for `create_model()` and `Scheduler.solve()`, ordered by payoff |
| [`known-defects.md`](known-defects.md) | concrete bugs, as opposed to plans |

## How numbers in these documents were obtained

Every figure here was measured, not estimated. The method, in the order it was applied:

1. **Work out the arithmetic bound first.** The objective is a sum of known terms, so the
   breaking point can usually be written down.
2. **Then build the adversarial case and run it through the real code path** — through
   `create_model()`/`Scheduler.solve()`, never a reimplementation of the objective.
3. **Then run a control** that differs in exactly one respect, to rule out the alternative
   explanation. A task that is dropped because the objective preferred something else and a
   task that is dropped because it never fit look identical in the output.
4. **Repeat anything timed.** A single timing is not a measurement; the figures below are
   three runs unless stated otherwise.

The one place this mattered most: the tier-dominance limit was first framed as
"routines × horizon days", which is **wrong**, and running it is what showed that. See
[`limits.md`](limits.md#1-tier-dominance).

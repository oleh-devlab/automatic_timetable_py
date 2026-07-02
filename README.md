# automatic_timetable_py

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white) ![OR-Tools 9.15+](https://img.shields.io/badge/OR--Tools-9.15%2B-orange?logo=google&logoColor=white)

The concept is the same as in the [`automatic_timetable`](https://github.com/oleh-devlab/automatic_timetable) repository, but it is written in Python and uses Google OR-Tools.

The previous version of `automatic_timetable` written in C++ has no external dependencies. Writing my own algorithms that take a large number of conditions into account and optimally solve an NP-hard problem takes quite a while, so I decided to try a ready-made solution.

## Features & Scheduling Logic

This project uses Google OR-Tools (CP-SAT solver) to schedule tasks around your fixed `time_blocks`. Below is a detailed description of the implemented scheduling rules and behaviors.

### 1. Pomodoro Chunking & Global Breaks
Tasks can be split into smaller work sessions (chunks) using `min_chunk_duration`, `max_chunk_duration`, and `break_duration`. 

- **Global Breaks:** The `break_duration` specified for a task creates a "global" blocked interval after the chunk. During this break, no other tasks can be scheduled.
- **Overlap with Fixed Blocks:** If your task's break interval hits a pre-scheduled fixed time block (like sleep or a meeting), the break will "merge" into it smoothly without demanding extra free time.
- **Remainder Chunks:** If a task's remaining time is less than `max_chunk_duration` but greater than or equal to `min_chunk_duration`, it will simply form a smaller valid chunk.

### 2. Deadlines
Tasks can have a `deadline` (e.g., `"30.06.2026 12:00"`).

- **Strict Limits:** The solver ensures that the task (and all of its chunks, if chunked) ends before the specified deadline.
- **All-or-Nothing Rule:** CP-SAT uses strict scheduling. If a task requires 120 minutes, but only 90 minutes are available before its deadline, the solver will completely skip the task rather than scheduling it partially. It will appear in the "Skipped tasks" output.

### 3. Priorities, Tiers & Early Placement
Tasks can have a `priority` (integer, default `1`). The mathematical model is designed and verified for the **0–10 range**. Exceeding priority 10 is mathematically safe due to the underlying Two-Stage architecture, but sticking to 0–10 is recommended for predictable visual sorting.

The solver uses a **2-Tier system** (based on `priority_threshold = 5`) to determine which tasks to schedule when there is a lack of free time.
- **High Tier (Priority >= 5):** Mandatory or critical tasks (e.g., University assignments).
- **Low Tier (Priority < 5):** Less critical, personal tasks.

**Behaviors and Resolutions (Two-Stage Architecture):**
To eliminate the combinatorial explosion and prevent time-bonuses from accidentally rejecting important tasks, the solver operates in two completely isolated stages:
1. **Stage 1 (Packer):** Selects the mathematically optimal set of tasks to fit into your schedule based strictly on Tiers and Deadlines.
2. **Stage 2 (Gravity):** Takes the locked set of tasks from Stage 1 and applies priority-based gravity to sort them visually (pushing them to the left).

**Key Rules:**
1. **Absolute Tier Dominance:** The solver mathematically guarantees that **any** single High Tier task is more valuable than **all** Low Tier tasks combined.
2. **Inside a Tier (Deadlines vs. Priorities):** Within the same tier, tasks are prioritized by their deadlines. A closer deadline always outweighs a distant one, regardless of priority.
3. **Early Placement Gravity:** In Stage 2, Priority acts as an exponential "gravity" multiplier. Higher priority tasks are pulled to the earliest available slots in your day (e.g., priority 9 will be automatically scheduled before priority 2).
4. **Chunk Minimization & Magnetic Grouping:** If a task is split into chunks, the solver naturally minimizes the number of chunks used to prevent over-fragmentation. It also applies a penalty for gaps, forcing chunks of the same task to stick closely together.
5. **Floating Tasks (Priority 0):** A priority of `0` removes the early-placement gravity entirely. These tasks act as "fillers" — they will be pushed to the evening or the end of the week, filling gaps without competing for your most productive morning slots.
6. **The Knapsack Phenomenon (Soft Priority):** Because Stage 1 maximizes the *total sum of weights*, if forced to choose between scheduling **ONE** urgent 2-hour task OR **THREE** less urgent 40-min tasks from the same tier, it will often choose the three tasks to maximize overall productivity.

### 4. Routines
Routines are recurring tasks that should be performed regularly (daily or weekly). Instead of creating them manually for every day, you define them once in the `"routines"` section of your `data.json`.
There are two types of routines:
- **Fixed-time routines**: Tied to a specific `time` (e.g., training every day at 07:00). These act like blocked intervals but represent tasks.
- **Flexible routines**: These behave like normal tasks with a `duration`, `priority`, and an optional `deadline_time` (e.g., study words before 18:00). The solver will find the optimal time for them within each day. Flexible routines do not support Pomodoro chunking (they are scheduled as a single block), but they do support `break_duration`.

## Project Structure

```text
automatic_timetable_py/
├── src/         # Core scheduling API library
├── tests/       # Unit tests
├── main.py      # Example consumer script running the API
└── data.json    # User data (tasks, time blocks, routines)
```

## Usage

To run the main application, use the following command from the root directory of the project:

```bash
python main.py
```

## Testing

To run all unit tests, use the `unittest discover` command from the root directory:

```bash
python -m unittest discover
```

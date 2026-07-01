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

### 3. Priorities & The 2-Tier Logic
Tasks can have a `priority` (integer, default `0`). The solver uses a **2-Tier system** (based on a `priority_threshold = 10`) to determine which tasks to schedule when there is a lack of free time.

- **High Tier (Priority >= 10):** These are mandatory or critical tasks (e.g., University assignments).
- **Low Tier (Priority < 10):** These are less critical, personal tasks.

**How Conflicts are Resolved:**
1. **Absolute Tier Dominance:** The solver mathematically guarantees that **any** High Tier task is more valuable than **all** Low Tier tasks combined. It will gladly drop hundreds of Low Tier tasks to ensure just one High Tier task is scheduled.
2. **Inside a Tier (Deadlines vs. Priorities):** Within the same tier, tasks are prioritized by their deadlines. A task due "today" has a much higher weight than a task due "next week", regardless of their priority values. Priority acts as a tiebreaker for tasks with deadlines on the same day, and as the main sorter for tasks without deadlines.
3. **The Knapsack Phenomenon (Soft Priority):** Because CP-SAT is a global optimizer, it maximizes the *total sum of weights*. This means that if it's forced to choose between scheduling **ONE** urgent task (e.g., 2 hours long) OR **THREE** less urgent tasks (e.g., 40 mins each) from the same tier, it will often choose to do the three tasks. This "soft priority" behavior ensures maximum productivity, rather than leaving giant holes in your schedule just to squeeze in one specific task. If a task is truly a life-and-death matter, simply give it a priority of 10 or higher to move it to the High Tier.

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

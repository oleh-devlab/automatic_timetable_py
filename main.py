import time
import os
from datetime import datetime

start_import_time = time.perf_counter()
import src.data_read as data_read  # noqa: E402
from src.scheduler import Scheduler  # noqa: E402

end_import_time = time.perf_counter()


def main():
    print(
        "Time taken to import Scheduler (including OR-Tools): {:.6f} seconds".format(
            end_import_time - start_import_time
        )
    )
    start_time_creating = time.perf_counter()

    data_path = os.path.join(os.path.dirname(__file__), "data.json")
    user_tasks, time_blocks, routines = data_read.load_data(data_path)

    scheduler = Scheduler(min_horizon_days=3, priority_threshold=5, step_minutes=5)

    for task in user_tasks:
        scheduler.add_task(task)

    for block in time_blocks:
        scheduler.add_time_block(block)

    for routine in routines:
        scheduler.add_routine(routine)

    end_time_creating = time.perf_counter()
    print("Time taken to load and create scheduler: {:.6f} seconds".format(end_time_creating - start_time_creating))

    start_time_solving = time.perf_counter()
    now = datetime.now().replace(second=0, microsecond=0)
    # now = datetime.strptime("06.07.2026", "%d.%m.%Y")

    result = scheduler.solve(start_time=now, timeouts={"packer": 7.0, "gravity": 3.0}, num_search_workers=8)
    end_time_solving = time.perf_counter()

    print("Time taken to solve the model: {:.6f} seconds".format(end_time_solving - start_time_solving))

    if result.is_successful:
        print(f"Status: {result.status}")
        print(f"Horizon used: {result.horizon} minutes ({result.horizon / 60 / 24:.2f} days)")

        events = []

        for sr in result.scheduled_routines:
            r_type = "Fixed Routine" if sr.routine_type == "fixed" else "Flexible Routine"
            events.append(
                {
                    "type": r_type,
                    "name": sr.task.name,
                    "start": sr.start_time,
                    "end": sr.end_time,
                    "duration": int(sr.task.duration.total_seconds() // 60),
                    "details": "",
                }
            )

        for stb in result.scheduled_timeblocks:
            events.append(
                {
                    "type": "Blocked Time",
                    "name": stb.name if stb.name else "Busy",
                    "start": stb.start_time,
                    "end": stb.end_time,
                    "duration": int((stb.end_time - stb.start_time).total_seconds() // 60),
                    "details": "",
                }
            )

        for st in result.scheduled_tasks:
            if st.chunks:
                for i, chunk in enumerate(st.chunks):
                    events.append(
                        {
                            "type": "Task Chunk",
                            "name": st.task.name,
                            "start": chunk.start_time,
                            "end": chunk.end_time,
                            "duration": int(chunk.duration.total_seconds() // 60),
                            "details": f" (Chunk {i+1}/{len(st.chunks)})",
                        }
                    )
            else:
                events.append(
                    {
                        "type": "Task",
                        "name": st.task.name,
                        "start": st.start_time,
                        "end": st.end_time,
                        "duration": int(st.task.duration.total_seconds() // 60),
                        "details": "",
                    }
                )

        events.sort(key=lambda x: x["start"], reverse=True)

        print("\n--- Schedule (From latest to earliest) ---")
        current_date = None
        for e in events:
            e_date = e["start"].date()
            if e_date != current_date:
                print(f"\n=== {e_date.strftime('%d.%m.%Y')} ===")
                current_date = e_date

            start_str = e["start"].strftime("%H:%M")
            end_str = (
                e["end"].strftime("%H:%M")
                if e["start"].date() == e["end"].date()
                else e["end"].strftime("%d.%m.%Y %H:%M")
            )
            print(f"  [{start_str} - {end_str}] {e['type']}: {e['name']}{e['details']} ({e['duration']} min)")

        if result.skipped_tasks:
            print(f"\n--- Skipped tasks ({len(result.skipped_tasks)}) ---")
            for st in result.skipped_tasks:
                deadline_info = f", deadline: {st.task.deadline}" if st.task.deadline else ""
                print(f"  {st.task.name} ({int(st.task.duration.total_seconds() // 60)} min{deadline_info})")

        if hasattr(result, "skipped_routines") and result.skipped_routines:
            print(f"\n--- Skipped routines ({len(result.skipped_routines)}) ---")
            for sr in result.skipped_routines:
                deadline_info = (
                    f", deadline: {sr.task.deadline.strftime('%d.%m %H:%M')}"
                    if getattr(sr.task, "deadline", None)
                    else ""
                )
                print(f"  {sr.task.name} ({int(sr.task.duration.total_seconds() // 60)} min{deadline_info})")
    else:
        print(f"{result.status}")


if __name__ == "__main__":
    main()

import time
import os
from datetime import datetime, timedelta

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

    scheduler = Scheduler(max_horizon_days=14, priority_threshold=10)

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
    result = scheduler.solve(start_time=now, timeout_seconds=0.5)
    end_time_solving = time.perf_counter()

    print("Time taken to solve the model: {:.6f} seconds".format(end_time_solving - start_time_solving))

    if result.is_successful:
        print(f"Status: {result.status}")

        events = []

        for r in result.fixed_routines:
            dt_str = f"{r.day.strftime('%Y-%m-%d')} {r.time}"
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            events.append(
                {
                    "type": "Fixed Routine",
                    "name": r.name,
                    "start": dt,
                    "end": dt + timedelta(minutes=r.duration),
                    "duration": r.duration,
                    "details": "",
                }
            )

        for sr in result.scheduled_routines:
            events.append(
                {
                    "type": "Flexible Routine",
                    "name": sr.task.name,
                    "start": sr.start_time,
                    "end": sr.end_time,
                    "duration": sr.task.duration,
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
                            "duration": chunk.duration,
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
                        "duration": st.task.duration,
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
                print(f"  {st.task.name} ({st.task.duration} min{deadline_info})")
    else:
        print("No solution found.")


if __name__ == "__main__":
    main()

import time
import os
from datetime import datetime

import data_read as data_read
from scheduler import Scheduler

def main():
    print("Initializing API Library...")
    start_time_creating = time.perf_counter()
    
    data_path = os.path.join(os.path.dirname(__file__), '../data.json')
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

        if result.fixed_routines:
            print(f"\nFixed Routines ({len(result.fixed_routines)}):")
            for r in result.fixed_routines:
                print(f"  {r.name} ({r.day.strftime('%d.%m.%Y')}): {r.time}, {r.duration} min")

        if result.scheduled_routines:
            print(f"\nFlexible Routines Scheduled ({len(result.scheduled_routines)}/{len(result.flexible_routines_info)}):")
            for sr in result.scheduled_routines:
                print(f"  Task: {sr.task.name}, Start: {sr.start_time.strftime('%d.%m.%Y %H:%M')}, End: {sr.end_time.strftime('%d.%m.%Y %H:%M')}")

        print(f"\nScheduled tasks ({len(result.scheduled_tasks)}/{len(user_tasks)}):")
        for st in result.scheduled_tasks:
            if st.chunks:
                print(f"  Task: {st.task.name} (chunked into {len(st.chunks)} parts)")
                for i, chunk in enumerate(st.chunks):
                    print(f"    Chunk {i+1}/{len(st.chunks)} ({chunk.duration} min): {chunk.start_time.strftime('%d.%m.%Y %H:%M')} — {chunk.end_time.strftime('%d.%m.%Y %H:%M')}")
            else:
                print(f"  Task: {st.task.name}, Start: {st.start_time.strftime('%d.%m.%Y %H:%M')}, End: {st.end_time.strftime('%d.%m.%Y %H:%M')}")

        if result.skipped_tasks:
            print(f"\nSkipped tasks ({len(result.skipped_tasks)}):")
            for st in result.skipped_tasks:
                deadline_info = f", deadline: {st.task.deadline}" if st.task.deadline else ""
                print(f"  Task: {st.task.name} ({st.task.duration} min{deadline_info}) — could not fit")
    else:
        print("No solution found.")

if __name__ == "__main__":
    main()
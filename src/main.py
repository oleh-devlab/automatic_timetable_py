import time
import os
from datetime import datetime
start_import_time = time.perf_counter()
from ortools.sat.python import cp_model
end_import_time = time.perf_counter()

from restrictions import create_model, calculate_horizon
from data_structs import Task
import data_read as data_read
from utils import parse_time_blocks, minutes_to_time
from routine_expansion import expand_routines

def main():
    print("Time taken to import OR-Tools.SAT: {:.6f} seconds".format(end_import_time - start_import_time))
    now = datetime.now().replace(second=0, microsecond=0)

    data_path = os.path.join(os.path.dirname(__file__), '../data.json')
    user_tasks, time_blocks_raw, routines = data_read.load_data(data_path)

    start_time_creating = time.perf_counter()
    # Convert HH:MM strings to minutes from now
    time_blocks = parse_time_blocks(time_blocks_raw, now)

    # Convert deadline strings to minutes from now
    for task in user_tasks:
        if task.deadline is not None:
            dt_deadline = datetime.strptime(task.deadline, "%d.%m.%Y %H:%M")
            task.deadline_min = int((dt_deadline - now).total_seconds() / 60)
        else:
            task.deadline_min = None
    
    horizon = calculate_horizon(user_tasks, max_horizon_days=14)

    extra_tasks, extra_blocks, routine_info = expand_routines(routines, now, horizon)
    user_tasks.extend(extra_tasks)
    time_blocks.extend(extra_blocks)

    model = create_model(user_tasks, time_blocks, horizon=horizon)
    end_time_creating = time.perf_counter()

    print("Time taken to create the model: {:.6f} seconds".format(end_time_creating - start_time_creating))

    solver = cp_model.CpSolver()
    # solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = 0.5
    start_time_solving = time.perf_counter()
    status = solver.solve(model)
    end_time_solving = time.perf_counter()

    print("Time taken to solve the model: {:.6f} seconds".format(end_time_solving - start_time_solving))

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"Status: {'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'}")

        scheduled = []
        skipped = []
        routines_scheduled = []
        for task in user_tasks:
            if solver.value(task.presence_var):
                start_val = solver.value(task.start_var)
                end_val = solver.value(task.end_var)
                start_time = minutes_to_time(start_val, now)
                end_time = minutes_to_time(end_val, now)
                if getattr(task, 'is_routine', False):
                    routines_scheduled.append((task, start_time, end_time))
                else:
                    scheduled.append((task, start_time, end_time))
            else:
                skipped.append(task)

        if routine_info:
            fixed_routines = [r for r in routine_info if r['type'] == 'fixed']
            if fixed_routines:
                print(f"\nFixed Routines ({len(fixed_routines)}):")
                for r in fixed_routines:
                    print(f"  {r['name']} ({r['day']}): {r['time']}, {r['duration']} min")

            flex_routines = [r for r in routine_info if r['type'] == 'flexible']
            if flex_routines or routines_scheduled:
                print(f"\nFlexible Routines Scheduled ({len(routines_scheduled)}/{len(flex_routines)}):")
                for task, start_time, end_time in routines_scheduled:
                    print(f"  Task: {task.name}, Start: {start_time}, End: {end_time}")

        base_task_count = len(user_tasks) - len([t for t in user_tasks if getattr(t, 'is_routine', False)])
        print(f"\nScheduled tasks ({len(scheduled)}/{base_task_count}):")
        for task, start_time, end_time in scheduled:
            if task.chunks:
                present_chunks = [c for c in task.chunks if solver.value(c['presence_var'])]
                print(f"  Task: {task.name} (chunked into {len(present_chunks)} parts)")
                for c, chunk in enumerate(task.chunks):
                    if solver.value(chunk['presence_var']):
                        cs = minutes_to_time(solver.value(chunk['start_var']), now)
                        ce = minutes_to_time(solver.value(chunk['end_var']), now)
                        csize = solver.value(chunk['size_var'])
                        print(f"    Chunk {c+1} ({csize} min): {cs} — {ce}")
            else:
                print(f"  Task: {task.name}, Start: {start_time}, End: {end_time}")

        if skipped:
            print(f"\nSkipped tasks ({len(skipped)}):")
            for task in skipped:
                deadline_info = f", deadline: {task.deadline}" if getattr(task, 'deadline', None) else ""
                print(f"  Task: {task.name} ({task.duration} min{deadline_info}) — could not fit")
    else:
        print("No solution found.")

if __name__ == "__main__":
    main()
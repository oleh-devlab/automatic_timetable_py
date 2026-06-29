import time
import os
from datetime import datetime
start_import_time = time.perf_counter()
from ortools.sat.python import cp_model
end_import_time = time.perf_counter()

from restrictions import create_model
from data_structs import Task
import data_read as data_read
from utils import parse_time_blocks, minutes_to_time

def main():
    now = datetime.now().replace(second=0, microsecond=0)

    data_path = os.path.join(os.path.dirname(__file__), '../data.json')
    user_tasks, time_blocks_raw = data_read.load_data(data_path)

    # Convert HH:MM strings to minutes from now
    time_blocks = parse_time_blocks(time_blocks_raw, now)

    # Convert deadline strings to minutes from now
    for task in user_tasks:
        if task.deadline is not None:
            dt_deadline = datetime.strptime(task.deadline, "%d.%m.%Y %H:%M")
            task.deadline_min = int((dt_deadline - now).total_seconds() / 60)
        else:
            task.deadline_min = None

    print("Time taken to import OR-Tools.SAT: {:.6f} seconds".format(end_import_time - start_import_time))

    start_time_creating = time.perf_counter()
    model = create_model(user_tasks, time_blocks)
    end_time_creating = time.perf_counter()

    print("Time taken to create the model: {:.6f} seconds".format(end_time_creating - start_time_creating))

    solver = cp_model.CpSolver()
    start_time_solving = time.perf_counter()
    status = solver.solve(model)
    end_time_solving = time.perf_counter()

    print("Time taken to solve the model: {:.6f} seconds".format(end_time_solving - start_time_solving))

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"Status: {'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'}")

        scheduled = []
        skipped = []
        for task in user_tasks:
            if solver.value(task.presence_var):
                start_val = solver.value(task.start_var)
                end_val = solver.value(task.end_var)
                start_time = minutes_to_time(start_val, now)
                end_time = minutes_to_time(end_val, now)
                scheduled.append((task, start_time, end_time))
            else:
                skipped.append(task)

        print(f"\nScheduled tasks ({len(scheduled)}/{len(user_tasks)}):")
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
                deadline_info = f", deadline: {task.deadline}" if task.deadline else ""
                print(f"  Task: {task.name} ({task.duration} min{deadline_info}) — could not fit")
    else:
        print("No solution found.")

if __name__ == "__main__":
    main()
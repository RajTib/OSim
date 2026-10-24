from collections import deque
from numbers import Integral

IDLE = "Idle"

ALGORITHMS = [
    "FCFS",
    "SJF (non-preemptive)",
    "SRTF (preemptive SJF)",
    "Priority (non-preemptive)",
    "Priority (preemptive)",
    "Round Robin",
]


def _is_int(value):
    # bool is a subclass of int, so reject it explicitly
    return isinstance(value, Integral) and not isinstance(value, bool)


def _pid(p):
    return str(p["pid"]).strip()


def validate_processes(processes):
    """Raise ValueError if the process list cannot be scheduled."""
    if not processes:
        raise ValueError("At least one process is required.")

    seen = set()
    for p in processes:
        pid = _pid(p)
        arrival, burst = p["arrival"], p["burst"]
        priority = p.get("priority", 0)

        if not pid:
            raise ValueError("Process ID cannot be empty.")
        if pid in seen:
            raise ValueError(f"Duplicate process ID: {pid}.")
        seen.add(pid)

        if not _is_int(arrival):
            raise ValueError(f"{pid}: arrival time must be an integer.")
        if not _is_int(burst):
            raise ValueError(f"{pid}: burst time must be an integer.")
        if not _is_int(priority):
            raise ValueError(f"{pid}: priority must be an integer.")
        if arrival < 0:
            raise ValueError(f"{pid}: arrival time cannot be negative.")
        if burst <= 0:
            raise ValueError(f"{pid}: burst time must be greater than 0.")
        if priority < 0:
            raise ValueError(f"{pid}: priority cannot be negative.")


def _validate_quantum(time_quantum):
    if not _is_int(time_quantum):
        raise ValueError("Time quantum must be an integer.")
    if time_quantum <= 0:
        raise ValueError("Time quantum must be greater than 0.")


def _add_segment(timeline, pid, start, end):
    """Append a Gantt segment, merging it with the previous one if it continues it."""
    if timeline and timeline[-1][0] == pid and timeline[-1][2] == start:
        timeline[-1] = (pid, timeline[-1][1], end)
    else:
        timeline.append((pid, start, end))


def _build_result(processes, completion, timeline):
    """Turn completion times and the timeline into the full metrics table plus averages."""
    first_start = {}
    for pid, start, _ in timeline:
        if pid != IDLE:
            first_start.setdefault(pid, start)

    rows = []
    for p in processes:  # keep the user's original input order
        pid = _pid(p)
        turnaround = completion[pid] - p["arrival"]
        rows.append({
            "pid": pid,
            "arrival": p["arrival"],
            "burst": p["burst"],
            "priority": p.get("priority", 0),
            "completion": completion[pid],
            "turnaround": turnaround,
            "waiting": turnaround - p["burst"],
            "response": first_start[pid] - p["arrival"],
        })

    n = len(rows)
    total_time = max(completion.values())
    busy = sum(end - start for pid, start, end in timeline if pid != IDLE)
    ran = [pid for pid, _, _ in timeline if pid != IDLE]
    switches = sum(1 for before, after in zip(ran, ran[1:]) if before != after)

    return {
        "timeline": timeline,
        "processes": rows,
        "avg_turnaround": sum(r["turnaround"] for r in rows) / n,
        "avg_waiting": sum(r["waiting"] for r in rows) / n,
        "avg_response": sum(r["response"] for r in rows) / n,
        "cpu_utilization": busy / total_time,
        "throughput": n / total_time,
        "context_switches": switches,
        "total_time": total_time,
    }


def fcfs(processes):
    """First Come First Served (non-preemptive).

    Run processes in order of arrival time; ties keep the input order.
    If the next process has not arrived yet, the CPU sits idle until it does.
    """
    validate_processes(processes)

    # sorted() is stable, so equal arrival times keep their input order
    order = sorted(processes, key=lambda p: p["arrival"])

    time = 0
    timeline = []
    completion = {}

    for p in order:
        pid = _pid(p)
        if time < p["arrival"]:
            timeline.append((IDLE, time, p["arrival"]))
            time = p["arrival"]
        timeline.append((pid, time, time + p["burst"]))
        time += p["burst"]
        completion[pid] = time

    return _build_result(processes, completion, timeline)


def _non_preemptive(processes, rank):
    """Shared loop for SJF and non-preemptive Priority.

    Whenever the CPU is free, pick the arrived process with the smallest
    rank(process) and run it to completion. `rank` returns a tuple, so ties
    fall through to arrival time and then input position.
    """
    waiting = list(enumerate(processes))  # (input position, process)
    time = 0
    timeline = []
    completion = {}

    while waiting:
        arrived = [(i, p) for i, p in waiting if p["arrival"] <= time]
        if not arrived:
            next_time = min(p["arrival"] for _, p in waiting)
            timeline.append((IDLE, time, next_time))
            time = next_time
            continue

        i, p = min(arrived, key=lambda ip: (*rank(ip[1]), ip[1]["arrival"], ip[0]))
        timeline.append((_pid(p), time, time + p["burst"]))
        time += p["burst"]
        completion[_pid(p)] = time
        waiting.remove((i, p))

    return _build_result(processes, completion, timeline)


def _preemptive(processes, rank):
    """Shared loop for SRTF and preemptive Priority.

    `rank(process, remaining_time)` gives the value to minimise. The scheduling
    decision can only change when a process arrives or finishes, so instead of
    stepping one time unit at a time we run the chosen process until the next
    arrival or its completion, whichever comes first.
    """
    remaining = {_pid(p): p["burst"] for p in processes}
    arrivals = sorted({p["arrival"] for p in processes})
    time = 0
    current = None  # pid that ran most recently (keeps the CPU on ties)
    timeline = []
    completion = {}

    while len(completion) < len(processes):
        arrived = [(i, p) for i, p in enumerate(processes)
                   if p["arrival"] <= time and _pid(p) not in completion]
        if not arrived:
            next_time = min(p["arrival"] for p in processes if _pid(p) not in completion)
            timeline.append((IDLE, time, next_time))
            time = next_time
            current = None
            continue

        # The running process wins ties (0 sorts before 1), so equal rank never preempts.
        _, p = min(arrived, key=lambda ip: (
            rank(ip[1], remaining[_pid(ip[1])]),
            0 if _pid(ip[1]) == current else 1,
            ip[1]["arrival"],
            ip[0],
        ))
        pid = _pid(p)
        later_arrivals = [a for a in arrivals if a > time]
        run = remaining[pid]
        if later_arrivals:
            run = min(run, later_arrivals[0] - time)

        _add_segment(timeline, pid, time, time + run)
        time += run
        remaining[pid] -= run
        current = pid
        if remaining[pid] == 0:
            completion[pid] = time

    return _build_result(processes, completion, timeline)


def sjf(processes):
    """Shortest Job First (non-preemptive): the shortest burst among arrived processes runs next."""
    validate_processes(processes)
    return _non_preemptive(processes, lambda p: (p["burst"],))


def srtf(processes):
    """Shortest Remaining Time First (preemptive SJF)."""
    validate_processes(processes)
    return _preemptive(processes, lambda p, remaining: remaining)


def priority_scheduling(processes, preemptive=False):
    """Priority scheduling. Lower number = higher priority.

    Non-preemptive: the chosen process runs its whole burst.
    Preemptive: a newly arrived process with a strictly higher priority takes the CPU.
    """
    validate_processes(processes)
    if preemptive:
        return _preemptive(processes, lambda p, remaining: p.get("priority", 0))
    return _non_preemptive(processes, lambda p: (p.get("priority", 0),))


def round_robin(processes, time_quantum):
    """Round Robin (preemptive) with a ready queue.

    Each process runs for at most `time_quantum` units, then goes to the back of
    the queue if it still has work left.

    Tie-break rule: if a process arrives at the same instant another process's
    quantum expires, the new arrival is queued BEFORE the preempted process.

    Every quantum slice is a separate timeline entry, so a process that runs
    twice in a row appears as two adjacent segments.
    """
    validate_processes(processes)
    _validate_quantum(time_quantum)

    order = sorted(processes, key=lambda p: p["arrival"])
    remaining = {_pid(p): p["burst"] for p in order}

    ready = deque()
    next_arrival = 0  # index into `order` of the next process that has not yet been queued
    time = 0
    timeline = []
    completion = {}

    def admit_arrivals():
        """Move every process that has arrived by `time` into the ready queue."""
        nonlocal next_arrival
        while next_arrival < len(order) and order[next_arrival]["arrival"] <= time:
            ready.append(_pid(order[next_arrival]))
            next_arrival += 1

    while len(completion) < len(order):
        admit_arrivals()

        if not ready:
            # Nothing is ready, so the CPU is idle until the next process arrives.
            next_time = order[next_arrival]["arrival"]
            timeline.append((IDLE, time, next_time))
            time = next_time
            continue

        pid = ready.popleft()
        run = min(time_quantum, remaining[pid])
        timeline.append((pid, time, time + run))
        time += run
        remaining[pid] -= run

        admit_arrivals()  # new arrivals go in before the preempted process
        if remaining[pid] > 0:
            ready.append(pid)
        else:
            completion[pid] = time

    return _build_result(processes, completion, timeline)


def run_algorithm(name, processes, time_quantum=2):
    """Run one of ALGORITHMS by its display name."""
    if name == "FCFS":
        return fcfs(processes)
    if name == "SJF (non-preemptive)":
        return sjf(processes)
    if name == "SRTF (preemptive SJF)":
        return srtf(processes)
    if name == "Priority (non-preemptive)":
        return priority_scheduling(processes, preemptive=False)
    if name == "Priority (preemptive)":
        return priority_scheduling(processes, preemptive=True)
    if name == "Round Robin":
        return round_robin(processes, time_quantum)
    raise ValueError(f"Unknown scheduling algorithm: {name}.")


def compare_algorithms(processes, time_quantum=2):
    """Run every algorithm on the same workload and return one summary row per algorithm."""
    rows = []
    for name in ALGORITHMS:
        result = run_algorithm(name, processes, time_quantum)
        rows.append({
            "algorithm": name,
            "avg_waiting": result["avg_waiting"],
            "avg_turnaround": result["avg_turnaround"],
            "avg_response": result["avg_response"],
            "cpu_utilization": result["cpu_utilization"],
            "throughput": result["throughput"],
            "context_switches": result["context_switches"],
            "total_time": result["total_time"],
        })
    return rows

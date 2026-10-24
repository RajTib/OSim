from numbers import Integral


def _is_count(value):
    return isinstance(value, Integral) and not isinstance(value, bool) and value >= 0


def _check_vector(vector, m, name):
    if len(vector) != m:
        raise ValueError(f"{name} must have {m} values (one per resource type).")
    if not all(_is_count(v) for v in vector):
        raise ValueError(f"{name} values must be non-negative integers.")


def _check_matrix(matrix, n, m, name):
    if len(matrix) != n:
        raise ValueError(f"{name} must have {n} rows (one per process).")
    for row in matrix:
        _check_vector(row, m, f"Each {name} row")


def _fits(need, work):
    return all(x <= w for x, w in zip(need, work))


def _add(a, b):
    return [x + y for x, y in zip(a, b)]


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _finish_loop(available, allocation, demand, finished):
    """Shared work/finish loop.

    demand[i] is what process i still needs (Need for Banker's, Request for detection).
    Returns (order of finished processes, step log, final finished flags).
    """
    work = list(available)
    finished = list(finished)
    order = []
    steps = []
    progress = True
    while progress:
        progress = False
        for i in range(len(allocation)):
            if not finished[i] and _fits(demand[i], work):
                new_work = _add(work, allocation[i])
                steps.append({"process": i, "work_before": work, "needs": list(demand[i]),
                              "releases": list(allocation[i]), "work_after": new_work})
                work = new_work
                finished[i] = True
                order.append(i)
                progress = True
    return order, steps, finished


# ---------------------------------------------------------------- Banker's algorithm

def need_matrix(maximum, allocation):
    return [_sub(mx, al) for mx, al in zip(maximum, allocation)]


def _validate_bankers(available, maximum, allocation):
    m = len(available)
    n = len(allocation)
    if m == 0 or n == 0:
        raise ValueError("At least one process and one resource type are required.")
    _check_vector(available, m, "Available")
    _check_matrix(allocation, n, m, "Allocation")
    _check_matrix(maximum, n, m, "Max")
    for i in range(n):
        if not _fits(allocation[i], maximum[i]):
            raise ValueError(f"P{i}: allocation cannot exceed its maximum claim.")


def bankers_safety(available, maximum, allocation):
    """Banker's safety algorithm.

    Returns {"safe": bool, "sequence": [process indices], "steps": [...], "need": matrix}.
    """
    _validate_bankers(available, maximum, allocation)
    need = need_matrix(maximum, allocation)
    order, steps, finished = _finish_loop(available, allocation, need, [False] * len(allocation))
    return {"safe": all(finished), "sequence": order, "steps": steps, "need": need}


def bankers_request(process, request, available, maximum, allocation):
    """Banker's resource-request algorithm for one request by `process` (an index).

    1. request <= need, otherwise it is an error (process exceeded its claim).
    2. request <= available, otherwise the process must wait.
    3. Pretend to allocate and run the safety algorithm; grant only if safe.

    Returns {"granted": bool, "reason": str, "safety": result or None,
             "available", "allocation"}  (the state after the decision).
    """
    _validate_bankers(available, maximum, allocation)
    n, m = len(allocation), len(available)
    if not (isinstance(process, Integral) and 0 <= process < n):
        raise ValueError("Unknown process.")
    _check_vector(request, m, "Request")

    need = need_matrix(maximum, allocation)
    if not _fits(request, need[process]):
        raise ValueError(f"P{process} asked for more than its remaining maximum claim {need[process]}.")
    if not _fits(request, available):
        return {"granted": False, "safety": None, "available": list(available),
                "allocation": [list(r) for r in allocation],
                "reason": f"Not enough resources available {list(available)}; P{process} must wait."}

    new_available = _sub(available, request)
    new_allocation = [list(r) for r in allocation]
    new_allocation[process] = _add(new_allocation[process], request)
    safety = bankers_safety(new_available, maximum, new_allocation)
    if safety["safe"]:
        sequence = ", ".join(f"P{i}" for i in safety["sequence"])
        return {"granted": True, "safety": safety, "available": new_available,
                "allocation": new_allocation,
                "reason": f"Granted: the new state is safe (safe sequence {sequence})."}
    return {"granted": False, "safety": safety, "available": list(available),
            "allocation": [list(r) for r in allocation],
            "reason": "Denied: granting it would leave the system in an unsafe state, "
                      f"so P{process} must wait."}


# ---------------------------------------------------------------- detection and recovery

def _validate_detection(available, allocation, request):
    m = len(available)
    n = len(allocation)
    if m == 0 or n == 0:
        raise ValueError("At least one process and one resource type are required.")
    _check_vector(available, m, "Available")
    _check_matrix(allocation, n, m, "Allocation")
    _check_matrix(request, n, m, "Request")


def detect_deadlock(available, allocation, request):
    """Deadlock detection for multiple-instance resources.

    A process holding nothing cannot be part of a deadlock, so it starts as finished.
    Returns {"deadlocked": [indices], "sequence": [indices that can finish], "steps": [...]}.
    """
    _validate_detection(available, allocation, request)
    finished = [not any(row) for row in allocation]
    order, steps, finished = _finish_loop(available, allocation, request, finished)
    deadlocked = [i for i, done in enumerate(finished) if not done]
    return {"deadlocked": deadlocked, "sequence": order, "steps": steps}


def explain_deadlock(deadlocked, allocation, request, process_names, resource_names):
    """Readable lines such as 'P1 holds R1 x1 and waits for R2 x1 (held by P2)'."""
    lines = []
    for i in deadlocked:
        held = [f"{resource_names[r]} x{c}" for r, c in enumerate(allocation[i]) if c]
        waits = []
        for r, c in enumerate(request[i]):
            if c:
                holders = [process_names[j] for j in deadlocked if j != i and allocation[j][r]]
                by = f" (held by {', '.join(holders)})" if holders else ""
                waits.append(f"{resource_names[r]} x{c}{by}")
        lines.append(f"{process_names[i]} holds {', '.join(held) or 'nothing'} "
                     f"and waits for {', '.join(waits) or 'nothing'}")
    return lines


def choose_victim(deadlocked, allocation):
    """Victim = the deadlocked process holding the most resource instances
    (killing it frees the most); ties go to the lowest index."""
    return min(deadlocked, key=lambda i: (-sum(allocation[i]), i))


def recover_by_termination(available, allocation, request):
    """Terminate victims one at a time until no deadlock remains.

    A terminated process releases everything it holds and its pending request
    is cancelled. Returns {"victims": [...], "available", "allocation", "request"}.
    """
    available = list(available)
    allocation = [list(r) for r in allocation]
    request = [list(r) for r in request]
    victims = []
    while True:
        deadlocked = detect_deadlock(available, allocation, request)["deadlocked"]
        if not deadlocked:
            break
        victim = choose_victim(deadlocked, allocation)
        available = _add(available, allocation[victim])
        allocation[victim] = [0] * len(available)
        request[victim] = [0] * len(available)
        victims.append(victim)
    return {"victims": victims, "available": available,
            "allocation": allocation, "request": request}

from numbers import Integral

POLICIES = ["FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"]
DIRECTIONS = ["up", "down"]


def _is_int(value):
    return isinstance(value, Integral) and not isinstance(value, bool)


def validate(requests, head, disk_size, direction="up"):
    if not _is_int(disk_size) or disk_size <= 0:
        raise ValueError("Number of cylinders must be a positive integer.")
    if not _is_int(head) or not 0 <= head < disk_size:
        raise ValueError(f"Head position must be between 0 and {disk_size - 1}.")
    if direction not in DIRECTIONS:
        raise ValueError("Direction must be 'up' or 'down'.")
    if not requests:
        raise ValueError("The request queue cannot be empty.")
    for r in requests:
        if not _is_int(r) or not 0 <= r < disk_size:
            raise ValueError(f"Every request must be a cylinder between 0 and {disk_size - 1}.")


def parse_requests(text):
    """Convert '98, 183 37' into [98, 183, 37]."""
    tokens = text.replace(",", " ").split()
    if not tokens:
        raise ValueError("The request queue cannot be empty.")
    try:
        return [int(t) for t in tokens]
    except ValueError:
        raise ValueError("Requests must be whole numbers separated by spaces or commas.") from None


def next_move(policy, head, direction, pending, disk_size):
    """Choose the next request to service.

    pending: list of cylinder numbers (in arrival order).
    Returns (index into pending, path, new_direction) where `path` is the list of
    cylinders the head visits, ending with the chosen request.
    """
    if policy not in POLICIES:
        raise ValueError(f"Unknown disk scheduling policy: {policy}.")
    if policy == "FCFS":
        return 0, [pending[0]], direction
    if policy == "SSTF":
        index = min(range(len(pending)), key=lambda i: (abs(pending[i] - head), pending[i], i))
        return index, [pending[index]], direction

    def nearest_ahead(position, moving):
        ahead = [i for i, c in enumerate(pending)
                 if (c >= position if moving == "up" else c <= position)]
        if not ahead:
            return None
        return min(ahead, key=lambda i: (abs(pending[i] - position), i))

    index = nearest_ahead(head, direction)
    if index is not None:
        return index, [pending[index]], direction

    # Nothing left in the current direction: turn around (or jump).
    edge = disk_size - 1 if direction == "up" else 0
    opposite_edge = 0 if direction == "up" else disk_size - 1
    reverse = "down" if direction == "up" else "up"

    if policy == "LOOK":
        index = nearest_ahead(head, reverse)
        return index, [pending[index]], reverse
    if policy == "SCAN":
        path = [edge] if head != edge else []
        index = nearest_ahead(edge, reverse)
        return index, path + [pending[index]], reverse
    if policy == "C-LOOK":
        # jump to the furthest request on the other side, keep the same direction
        index = nearest_ahead(opposite_edge, direction)
        return index, [pending[index]], direction
    # C-SCAN
    path = [edge] if head != edge else []
    path.append(opposite_edge)
    index = nearest_ahead(opposite_edge, direction)
    if pending[index] != opposite_edge:
        path.append(pending[index])
    return index, path, direction


def path_distance(start, path):
    total = 0
    position = start
    for cylinder in path:
        total += abs(cylinder - position)
        position = cylinder
    return total


def schedule(policy, requests, head, disk_size=200, direction="up"):
    """Service all requests with one policy.

    Returns {
        "policy", "order": [requests in service order],
        "path": [head, ... every cylinder visited, including edges],
        "total_movement": int,
        "steps": [ {from, to, distance, serviced}, ... ],
    }
    """
    validate(requests, head, disk_size, direction)
    pending = list(requests)
    position = head
    path = [head]
    order = []
    steps = []
    total = 0

    while pending:
        index, moves, direction = next_move(policy, position, direction, pending, disk_size)
        serviced = pending.pop(index)
        for i, cylinder in enumerate(moves):
            distance = abs(cylinder - position)
            is_request = i == len(moves) - 1
            steps.append({"from": position, "to": cylinder, "distance": distance,
                          "serviced": serviced if is_request else None})
            total += distance
            position = cylinder
            path.append(cylinder)
        order.append(serviced)

    return {"policy": policy, "order": order, "path": path,
            "total_movement": total, "steps": steps}


def compare_policies(requests, head, disk_size=200, direction="up"):
    rows = []
    for name in POLICIES:
        result = schedule(name, requests, head, disk_size, direction)
        rows.append({
            "policy": name,
            "total_movement": result["total_movement"],
            "order": " → ".join(str(c) for c in result["order"]),
        })
    return rows

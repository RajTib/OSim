from numbers import Integral

STRATEGIES = ["First Fit", "Best Fit", "Worst Fit"]
MODES = ["variable", "fixed"]


def _is_positive_int(value):
    return isinstance(value, Integral) and not isinstance(value, bool) and value > 0


def _validate(blocks, requests, strategy, mode):
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {strategy}.")
    if mode not in MODES:
        raise ValueError(f"Unknown allocation model: {mode}.")
    if not blocks:
        raise ValueError("At least one memory block is required.")
    for size in blocks:
        if not _is_positive_int(size):
            raise ValueError("Memory block sizes must be positive integers.")
    if not requests:
        raise ValueError("At least one process request is required.")
    seen = set()
    for r in requests:
        pid = str(r["pid"]).strip()
        if not pid:
            raise ValueError("Process name cannot be empty.")
        if pid in seen:
            raise ValueError(f"Duplicate process name: {pid}.")
        seen.add(pid)
        if not _is_positive_int(r["size"]):
            raise ValueError(f"{pid}: requested size must be a positive integer.")


def _pick_block(candidates, strategy):
    """candidates: list of (block index, free space). Return the chosen block index."""
    if strategy == "First Fit":
        return min(candidates)[0]
    if strategy == "Best Fit":
        return min(candidates, key=lambda c: (c[1], c[0]))[0]
    return min(candidates, key=lambda c: (-c[1], c[0]))[0]  # Worst Fit


def allocate(blocks, requests, strategy="First Fit", mode="variable"):
    """Allocate each request {"pid", "size"} to a block.

    Returns:
        {
            "strategy", "mode",
            "allocations": [ {pid, size, block (0-based index or None)}, ... ],
            "blocks": [ {block, size, free, segments: [(pid, size), ...]}, ... ],
            "unallocated": [pid, ...],
            "total_free": int,           # free memory still usable by new processes
            "largest_free": int,         # biggest single usable piece
            "internal_fragmentation": int or None (None in the variable model),
            "external_fragmentation": int,
        }
    """
    _validate(blocks, requests, strategy, mode)

    state = [{"block": i, "size": size, "free": size, "segments": []}
             for i, size in enumerate(blocks)]
    allocations = []
    unallocated = []

    for r in requests:
        pid, size = str(r["pid"]).strip(), r["size"]
        if mode == "variable":
            candidates = [(b["block"], b["free"]) for b in state if b["free"] >= size]
        else:  # fixed: only empty partitions, measured by their full size
            candidates = [(b["block"], b["size"]) for b in state
                          if not b["segments"] and b["size"] >= size]

        if not candidates:
            allocations.append({"pid": pid, "size": size, "block": None})
            unallocated.append(pid)
            continue

        chosen = state[_pick_block(candidates, strategy)]
        chosen["segments"].append((pid, size))
        chosen["free"] -= size
        allocations.append({"pid": pid, "size": size, "block": chosen["block"]})

    if mode == "variable":
        usable = [b["free"] for b in state]
        internal = None
    else:
        # In fixed partitioning, space left inside an occupied block cannot be used.
        usable = [b["size"] for b in state if not b["segments"]]
        internal = sum(b["free"] for b in state if b["segments"])

    total_free = sum(usable)
    largest_free = max(usable, default=0)
    sizes = {a["pid"]: a["size"] for a in allocations}
    blocked_by_fragmentation = any(sizes[pid] <= total_free for pid in unallocated)

    return {
        "strategy": strategy,
        "mode": mode,
        "allocations": allocations,
        "blocks": state,
        "unallocated": unallocated,
        "total_free": total_free,
        "largest_free": largest_free,
        "internal_fragmentation": internal,
        "external_fragmentation": total_free if blocked_by_fragmentation else 0,
    }


def compare_strategies(blocks, requests, mode="variable"):
    """Run all three strategies on the same input; one summary row each."""
    rows = []
    for name in STRATEGIES:
        result = allocate(blocks, requests, name, mode)
        rows.append({
            "strategy": name,
            "allocated": len(requests) - len(result["unallocated"]),
            "unallocated": ", ".join(result["unallocated"]) or "-",
            "total_free": result["total_free"],
            "largest_free": result["largest_free"],
            "internal_fragmentation": result["internal_fragmentation"],
            "external_fragmentation": result["external_fragmentation"],
        })
    return rows

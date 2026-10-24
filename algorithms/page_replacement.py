from numbers import Integral

ALGORITHMS = ["FIFO", "LRU", "Optimal"]


def parse_reference_string(text):
    """Convert text like '7 0 1, 2 0' into [7, 0, 1, 2, 0]."""
    tokens = text.replace(",", " ").split()
    if not tokens:
        raise ValueError("Page reference sequence cannot be empty.")
    try:
        return [int(t) for t in tokens]
    except ValueError:
        raise ValueError(
            "Page references must be whole numbers separated by spaces or commas."
        ) from None


def _validate(reference, num_frames):
    if isinstance(num_frames, bool) or not isinstance(num_frames, Integral):
        raise ValueError("Number of frames must be an integer.")
    if num_frames <= 0:
        raise ValueError("Number of frames must be greater than 0.")
    if not reference:
        raise ValueError("Page reference sequence cannot be empty.")
    for page in reference:
        if isinstance(page, bool) or not isinstance(page, Integral) or page < 0:
            raise ValueError("Page numbers must be non-negative integers.")


def _next_use(reference, page, after):
    """Index of the next reference to `page` after position `after`, or None if never used again."""
    for j in range(after + 1, len(reference)):
        if reference[j] == page:
            return j
    return None


def _choose_victim(algorithm, frames, loaded_at, last_used, reference, i):
    """Return the index of the frame to overwrite (all frames are full)."""
    slots = range(len(frames))
    if algorithm == "FIFO":
        return min(slots, key=lambda f: loaded_at[f])
    if algorithm == "LRU":
        return min(slots, key=lambda f: last_used[f])

    # Optimal: "never used again" counts as infinitely far away.
    def distance(f):
        nxt = _next_use(reference, frames[f], i)
        return float("inf") if nxt is None else nxt

    return max(slots, key=lambda f: (distance(f), -loaded_at[f]))


def page_replacement(reference, num_frames, algorithm="FIFO"):
    """Simulate a page replacement algorithm ("FIFO", "LRU" or "Optimal").

    Returns:
        {
            "algorithm": str,
            "steps": [ {step, page, frames, hit, replaced, loaded_into}, ... ],
            "hits": int, "faults": int,
            "hit_ratio": float, "fault_ratio": float,
        }
    `frames` in each step is a snapshot AFTER that reference (None = empty frame).
    `replaced` is the evicted page on a fault with full frames, otherwise None.
    `loaded_into` is the index of the frame that received the page on a fault,
    or None on a hit.
    """
    if algorithm not in ALGORITHMS:
        raise ValueError(f"Unknown page replacement algorithm: {algorithm}.")
    _validate(reference, num_frames)

    frames = [None] * num_frames
    loaded_at = [None] * num_frames  # position at which each frame's page was loaded
    last_used = [None] * num_frames  # position at which each frame's page was last referenced
    hits = 0
    faults = 0
    steps = []

    for i, page in enumerate(reference):
        replaced = None
        loaded_into = None
        if page in frames:
            hit = True
            hits += 1
            last_used[frames.index(page)] = i
        else:
            hit = False
            faults += 1
            if None in frames:
                loaded_into = frames.index(None)  # lowest free frame
            else:
                loaded_into = _choose_victim(algorithm, frames, loaded_at, last_used, reference, i)
                replaced = frames[loaded_into]
            frames[loaded_into] = page
            loaded_at[loaded_into] = i
            last_used[loaded_into] = i

        steps.append({
            "step": i + 1,
            "page": page,
            "frames": list(frames),  # copy, because `frames` keeps changing
            "hit": hit,
            "replaced": replaced,
            "loaded_into": loaded_into,
        })

    total = len(reference)
    return {
        "algorithm": algorithm,
        "steps": steps,
        "hits": hits,
        "faults": faults,
        "hit_ratio": hits / total,
        "fault_ratio": faults / total,
    }


def fifo_page_replacement(reference, num_frames):
    return page_replacement(reference, num_frames, "FIFO")


def lru_page_replacement(reference, num_frames):
    return page_replacement(reference, num_frames, "LRU")


def optimal_page_replacement(reference, num_frames):
    return page_replacement(reference, num_frames, "Optimal")


def compare_page_replacement(reference, num_frames):
    """Run all three algorithms on the same input; one summary row each."""
    rows = []
    for name in ALGORITHMS:
        result = page_replacement(reference, num_frames, name)
        rows.append({
            "algorithm": name,
            "hits": result["hits"],
            "faults": result["faults"],
            "fault_ratio": result["fault_ratio"],
        })
    return rows

"""Resource manager: resource types with a fixed number of instances.

It keeps the real accounting (who holds what, who is waiting for what) and
refuses invalid operations:
    * unknown resources or non-positive counts,
    * a process holding more instances of a type than exist,
    * releasing instances a process does not hold,
    * a process making a second request while it is already waiting.

Invariant (always true): available[r] + sum of held[*][r] == total[r].

Waiting requests are granted in FIFO order; a request that does not fit yet is
skipped so that a later, smaller request can still be granted.

Deadlock detection converts this state into the matrix form and uses
algorithms.deadlock.detect_deadlock.
"""

from numbers import Integral

from algorithms.deadlock import choose_victim, detect_deadlock, explain_deadlock


def parse_resources(text):
    """'printer=1, scanner=2' -> {'printer': 1, 'scanner': 2}"""
    totals = {}
    for item in text.replace("\n", ",").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"Resources must look like name=count, got {item!r}.")
        name, count = (s.strip() for s in item.split("=", 1))
        try:
            totals[name] = int(count)
        except ValueError:
            raise ValueError(f"Resource count for {name!r} must be a whole number.") from None
    return totals


class ResourceManager:
    def __init__(self, totals):
        if not totals:
            raise ValueError("At least one resource type is required.")
        for name, count in totals.items():
            if not str(name).strip() or " " in str(name):
                raise ValueError(f"Invalid resource name: {name!r}.")
            if isinstance(count, bool) or not isinstance(count, Integral) or count <= 0:
                raise ValueError(f"{name}: number of instances must be a positive integer.")
        self.totals = dict(totals)
        self.available = dict(totals)
        self.held = {}      # pid -> {resource: count}
        self.waiting = []   # FIFO list of {"pid", "resource", "count"}

    @property
    def names(self):
        return list(self.totals)

    def add_process(self, pid):
        self.held.setdefault(pid, {})

    def _check(self, pid, resource, count):
        if pid not in self.held:
            raise ValueError(f"Unknown process: {pid}.")
        if resource not in self.totals:
            raise ValueError(f"Unknown resource: {resource}.")
        if isinstance(count, bool) or not isinstance(count, Integral) or count <= 0:
            raise ValueError("Count must be a positive integer.")

    def holding(self, pid, resource):
        return self.held[pid].get(resource, 0)

    def waiting_for(self, pid):
        for w in self.waiting:
            if w["pid"] == pid:
                return w
        return None

    def request(self, pid, resource, count):
        """Grant immediately (return True) or queue the request (return False)."""
        self._check(pid, resource, count)
        if self.waiting_for(pid):
            raise ValueError(f"{pid} is already waiting for a resource.")
        if self.holding(pid, resource) + count > self.totals[resource]:
            raise ValueError(
                f"{pid} would hold more {resource} than exist ({self.totals[resource]}).")
        if count <= self.available[resource]:
            self._give(pid, resource, count)
            return True
        self.waiting.append({"pid": pid, "resource": resource, "count": count})
        return False

    def _give(self, pid, resource, count):
        self.available[resource] -= count
        self.held[pid][resource] = self.holding(pid, resource) + count

    def release(self, pid, resource, count):
        self._check(pid, resource, count)
        if self.holding(pid, resource) < count:
            raise ValueError(
                f"{pid} cannot release {count} {resource}: it holds {self.holding(pid, resource)}.")
        self.held[pid][resource] -= count
        if self.held[pid][resource] == 0:
            del self.held[pid][resource]
        self.available[resource] += count

    def release_all(self, pid):
        """Release everything pid holds and cancel its waiting request. Returns what was released."""
        released = dict(self.held.get(pid, {}))
        for resource, count in released.items():
            self.release(pid, resource, count)
        self.cancel_wait(pid)
        return released

    def cancel_wait(self, pid):
        self.waiting = [w for w in self.waiting if w["pid"] != pid]

    def grant_waiting(self):
        """Grant every waiting request that now fits, in FIFO order. Returns the granted requests."""
        granted = []
        for w in list(self.waiting):
            if w["count"] <= self.available[w["resource"]]:
                self._give(w["pid"], w["resource"], w["count"])
                self.waiting.remove(w)
                granted.append(w)
        return granted

    # ------------------------------------------------------------ matrix view and deadlocks

    def matrices(self, pids=None):
        """Return (pids, resources, available vector, allocation matrix, request matrix)."""
        pids = list(self.held) if pids is None else list(pids)
        names = self.names
        available = [self.available[r] for r in names]
        allocation = [[self.holding(p, r) for r in names] for p in pids]
        request = []
        for p in pids:
            w = self.waiting_for(p)
            request.append([w["count"] if w and w["resource"] == r else 0 for r in names])
        return pids, names, available, allocation, request

    def detect(self, pids=None):
        """Run deadlock detection. Returns {"deadlocked": [pids], "explanation": [lines]}."""
        pids, names, available, allocation, request = self.matrices(pids)
        if not pids:
            return {"deadlocked": [], "explanation": []}
        found = detect_deadlock(available, allocation, request)["deadlocked"]
        return {
            "deadlocked": [pids[i] for i in found],
            "explanation": explain_deadlock(found, allocation, request, pids, names),
        }

    def pick_victim(self, deadlocked_pids):
        """Choose which deadlocked process to terminate (holds the most instances; ties -> first)."""
        allocation = [[self.holding(p, r) for r in self.names] for p in deadlocked_pids]
        return deadlocked_pids[choose_victim(list(range(len(deadlocked_pids))), allocation)]

    def check_invariants(self):
        for r, total in self.totals.items():
            held = sum(h.get(r, 0) for h in self.held.values())
            if self.available[r] + held != total or self.available[r] < 0:
                raise AssertionError(f"Resource accounting broken for {r}.")

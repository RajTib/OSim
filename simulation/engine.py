"""The integrated simulation: one shared system state advanced in discrete ticks.

All subsystems below live inside ONE Simulation object and act on the same processes:

    CPU scheduler      picks which Ready process runs during each tick
    PagedMemory        MEM instructions hit or page-fault; a fault blocks the process
    ResourceManager    REQ may block the process until another process releases
    VirtualFileSystem  READ/WRITE are validated against it and applied when the I/O ends
    Disk               file I/O becomes a disk request serviced by a disk-scheduling policy

Order of work inside one tick t (step()):
    1. Finish page-ins whose time is up      -> page table updated, process Blocked -> Ready
    2. Finish the disk request if it is done  -> file system updated, process Blocked -> Ready
    3. Admit processes whose arrival time is t  (New -> Ready)
    4. Grant waiting resource requests that now fit (Blocked -> Ready)
    5. If the disk is idle, start the next request chosen by the disk policy
    6. Scheduling: preempt the running process if the policy says so, then
       dispatch a Ready process if the CPU is free
    7. Execute ONE tick of the running process's current instruction
       (this may block it, terminate it, or create a page-in / disk request)
    8. Record the tick: per-process state, waiting/blocked time, CPU timeline
    9. clock = t + 1
   10. Deadlock detection on the resource state, between ticks (optional
       automatic recovery; manual recovery also happens between ticks)
Processes that become Ready in the same step join the ready queue in the order
listed above (so in Round Robin a process woken in step 1-4 is queued before a
process preempted in step 6). Within one step, processes are handled in
workload order.

Timing rules:
    * Every instruction that is executed uses one CPU tick, including the tick
      in which a process issues a request that then blocks it.
    * A page fault in tick t blocks the process for `page_fault_ticks` ticks;
      the page-in completes at the start of tick t + 1 + page_fault_ticks.
      The faulting access is completed by the page-in (no retry needed).
      Page-ins happen in parallel and do not use the disk queue (a simplification).
    * The victim frame is chosen when the page-in completes.
    * A disk request takes 1 + ceil(seek distance / seek_rate) ticks.
    * A failed file operation (e.g. reading a missing file) does not block:
      an IO_ERROR event is logged and the process continues, like a system
      call returning an error.
"""

import math
from collections import deque
from dataclasses import dataclass, field

from algorithms.cpu_scheduling import ALGORITHMS as SCHEDULERS
from algorithms.disk_scheduling import DIRECTIONS, POLICIES as DISK_POLICIES, next_move, path_distance
from filesystem.vfs import FileSystemError
from simulation.memory import ONLINE_POLICIES, PagedMemory
from simulation.process import (BLOCKED, NEW, PCB, READY, RUNNING, STATES, TERMINATED,
                                format_instruction)
from simulation.resources import ResourceManager
from simulation.workload import build_file_system, validate_workload

IDLE = "Idle"


@dataclass
class SimConfig:
    scheduler: str = "Round Robin"
    quantum: int = 2
    num_frames: int = 3
    page_policy: str = "FIFO"
    page_fault_ticks: int = 2
    disk_policy: str = "SSTF"
    disk_cylinders: int = 200
    disk_head: int = 100
    disk_direction: str = "up"
    seek_rate: int = 50          # cylinders the head moves per tick
    disk_blocks: int = 64
    block_size: int = 16
    resources: dict = field(default_factory=lambda: {"printer": 1})
    auto_recover: bool = False   # automatically kill a deadlock victim when a deadlock is found

    def validate(self):
        if self.scheduler not in SCHEDULERS:
            raise ValueError(f"Unknown scheduler: {self.scheduler}.")
        if self.quantum <= 0:
            raise ValueError("Time quantum must be greater than 0.")
        if self.num_frames <= 0:
            raise ValueError("Number of frames must be greater than 0.")
        if self.page_policy not in ONLINE_POLICIES:
            raise ValueError("Page replacement in the simulation must be FIFO or LRU.")
        if self.page_fault_ticks <= 0:
            raise ValueError("Page-fault service time must be at least 1 tick.")
        if self.disk_policy not in DISK_POLICIES:
            raise ValueError(f"Unknown disk policy: {self.disk_policy}.")
        if self.disk_cylinders <= 0:
            raise ValueError("Number of cylinders must be greater than 0.")
        if not 0 <= self.disk_head < self.disk_cylinders:
            raise ValueError("Initial head position must be a valid cylinder.")
        if self.disk_direction not in DIRECTIONS:
            raise ValueError("Disk direction must be 'up' or 'down'.")
        if self.seek_rate <= 0:
            raise ValueError("Seek rate must be greater than 0.")
        if self.disk_blocks <= 0 or self.block_size <= 0:
            raise ValueError("Disk blocks and block size must be greater than 0.")


class Simulation:
    def __init__(self, config, processes, files=None):
        config.validate()
        self.config = config
        self.resources = ResourceManager(config.resources)  # validates resource totals
        validate_workload(processes, config.resources)

        self.clock = 0
        self.processes = {}  # pid -> PCB, in workload order
        self.ready = deque()
        self.running = None
        self.last_ran = None
        self.quantum_used = 0
        self.context_switches = 0

        self.memory = PagedMemory(config.num_frames, config.page_policy)
        self.vfs = build_file_system(files or {}, config.disk_blocks, config.block_size)
        self.page_ins = []   # pending page-ins: {"pid", "page", "done_at"}
        self.disk = {
            "head": config.disk_head,
            "direction": config.disk_direction,
            "queue": [],         # waiting requests: {"pid", "op", "path", "data", "cylinder", "issued"}
            "current": None,     # {"request", "started", "done_at"}
            "movement": 0,
            "path": [config.disk_head],
            "completed": 0,
        }
        self.io_completed = 0
        self.io_errors = 0

        self.events = []
        self.cpu_timeline = []   # pid (or IDLE) that ran in each tick
        self.state_history = []  # per tick: {pid: state during that tick}
        self.deadlocked = []

        for p in processes:
            pcb = PCB(p["pid"], p["arrival"], p["priority"], p["pages"], p["program"])
            self.processes[pcb.pid] = pcb
            self.memory.add_process(pcb.pid, pcb.num_pages)
            self.resources.add_process(pcb.pid)

        self.log("SYSTEM", None, "INIT",
                 f"{len(self.processes)} processes, scheduler {config.scheduler}, "
                 f"{config.num_frames} frames ({config.page_policy}), disk {config.disk_policy}, "
                 f"resources {config.resources}")

    # ------------------------------------------------------------ helpers

    def log(self, subsystem, pid, event, details, tick=None):
        self.events.append({"tick": self.clock if tick is None else tick, "subsystem": subsystem,
                            "pid": pid or "", "event": event, "details": details})

    def _block(self, pcb, reason):
        pcb.transition(BLOCKED)
        pcb.blocked_reason = reason
        self.running = None
        self.log("PROCESS", pcb.pid, "BLOCK", reason)

    def _wake(self, pcb, reason):
        pcb.transition(READY)
        pcb.blocked_reason = None
        self.ready.append(pcb.pid)
        self.log("PROCESS", pcb.pid, "WAKE", f"{reason}; back in the ready queue")

    def _terminate(self, pcb, completion, reason="finished"):
        if self.running == pcb.pid:
            self.running = None
        if pcb.pid in self.ready:
            self.ready.remove(pcb.pid)
        pcb.transition(TERMINATED)
        pcb.completion = completion
        pcb.exit_reason = reason
        pcb.blocked_reason = None
        released = self.resources.release_all(pcb.pid)
        freed = self.memory.free_process(pcb.pid)
        self.page_ins = [op for op in self.page_ins if op["pid"] != pcb.pid]
        details = f"{reason} at time {completion}"
        if released:
            details += "; released " + ", ".join(f"{r} x{c}" for r, c in released.items())
        if freed:
            details += f"; freed frames {freed}"
        self.log("PROCESS", pcb.pid, "EXIT", details)

    def _instruction_done(self, pcb, completion_if_last):
        """Advance pcb past its current instruction; terminate it if that was the last one.
        Returns True if the process terminated."""
        if pcb.finish_instruction():
            self._terminate(pcb, completion_if_last)
            return True
        return False

    def _cylinder_for(self, path):
        """Map a file to a cylinder: its first block, or the first free block for a new/empty file."""
        if self.vfs.is_file(path) and self.vfs.file_blocks(path):
            block = self.vfs.file_blocks(path)[0]
        elif self.vfs.free_blocks:
            block = min(self.vfs.free_blocks)
        else:
            block = 0
        return block * self.config.disk_cylinders // self.config.disk_blocks

    # ------------------------------------------------------------ the tick

    def is_finished(self):
        return all(p.state == TERMINATED for p in self.processes.values())

    def can_progress(self):
        """False when no tick could ever change anything (finished, or stuck)."""
        if self.is_finished():
            return False
        grantable = any(w["count"] <= self.resources.available[w["resource"]]
                        for w in self.resources.waiting)  # will be granted next tick
        return bool(self.running or self.ready or self.page_ins or self.disk["current"]
                    or self.disk["queue"] or grantable
                    or any(p.state == NEW for p in self.processes.values()))

    @property
    def status(self):
        if self.is_finished():
            return "finished"
        if self.deadlocked:
            return "deadlocked"
        if not self.can_progress():
            return "stalled"
        return "running"

    def step(self):
        """Advance the simulation by exactly one tick. Returns False if already finished."""
        if self.is_finished():
            return False
        t = self.clock
        self._ran = None
        self._complete_page_ins(t)
        self._complete_disk(t)
        self._admit_arrivals(t)
        self._grant_resources()
        self._start_disk(t)
        self._schedule(t)
        self._execute(t)
        self._record_tick()
        self.clock = t + 1
        self._check_deadlock()  # at the boundary between tick t and t + 1
        return True

    def run(self, max_ticks=500):
        """Step until finished, stuck (deadlock with nothing else to do) or max_ticks ticks."""
        ticks = 0
        while ticks < max_ticks and self.can_progress():
            self.step()
            ticks += 1
        return ticks

    # step 1
    def _complete_page_ins(self, t):
        done = [op for op in self.page_ins if op["done_at"] == t]
        self.page_ins = [op for op in self.page_ins if op["done_at"] != t]
        for op in done:
            pcb = self.processes[op["pid"]]
            frame, evicted = self.memory.load(pcb.pid, op["page"], t)
            if evicted:
                self.log("MEMORY", evicted[0], "EVICT",
                         f"page {evicted[1]} of {evicted[0]} evicted from frame {frame} "
                         f"({self.memory.policy})")
            self.log("MEMORY", pcb.pid, "PAGE_IN", f"page {op['page']} loaded into frame {frame}")
            if not self._instruction_done(pcb, completion_if_last=t):
                self._wake(pcb, "page-in complete")

    # step 2
    def _complete_disk(self, t):
        current = self.disk["current"]
        if current is None or current["done_at"] != t:
            return
        self.disk["current"] = None
        self.disk["completed"] += 1
        req = current["request"]
        pcb = self.processes[req["pid"]]
        try:
            if req["op"] == "READ":
                content = self.vfs.read_file(req["path"])
                self.log("FILE", pcb.pid, "READ_DONE", f"read {len(content)} characters from {req['path']}")
            else:
                if self.vfs.is_file(req["path"]):
                    self.vfs.write_file(req["path"], req["data"], append=True)
                else:
                    self.vfs.create_file(req["path"], req["data"])
                info = self.vfs.stat(req["path"])
                self.log("FILE", pcb.pid, "WRITE_DONE",
                         f"wrote {len(req['data'])} characters to {req['path']} "
                         f"(now {info['size']} characters, blocks {info['blocks']})")
            self.io_completed += 1
        except FileSystemError as error:  # e.g. the disk filled up after the request was issued
            self.io_errors += 1
            self.log("FILE", pcb.pid, "IO_ERROR", str(error))
        self.log("DISK", pcb.pid, "DONE", f"{req['op']} {req['path']} finished")
        if pcb.state == BLOCKED and not self._instruction_done(pcb, completion_if_last=t):
            self._wake(pcb, "disk I/O complete")

    # step 3
    def _admit_arrivals(self, t):
        arrivals = [p for p in self.processes.values() if p.state == NEW and p.arrival <= t]
        for pcb in sorted(arrivals, key=lambda p: p.arrival):  # stable: ties keep workload order
            pcb.transition(READY)
            self.ready.append(pcb.pid)
            self.log("PROCESS", pcb.pid, "ARRIVE", "admitted to the ready queue")

    # step 4
    def _grant_resources(self):
        for w in self.resources.grant_waiting():
            pcb = self.processes[w["pid"]]
            self.log("RESOURCE", pcb.pid, "GRANT", f"{w['resource']} x{w['count']} granted after waiting")
            if not self._instruction_done(pcb, completion_if_last=self.clock):
                self._wake(pcb, f"got {w['resource']}")

    # step 5
    def _start_disk(self, t):
        disk = self.disk
        if disk["current"] is not None or not disk["queue"]:
            return
        cylinders = [r["cylinder"] for r in disk["queue"]]
        index, path, direction = next_move(self.config.disk_policy, disk["head"], disk["direction"],
                                           cylinders, self.config.disk_cylinders)
        req = disk["queue"].pop(index)
        distance = path_distance(disk["head"], path)
        duration = 1 + math.ceil(distance / self.config.seek_rate)
        route = " → ".join(str(c) for c in [disk["head"]] + path)
        disk["head"] = path[-1]
        disk["direction"] = direction
        disk["movement"] += distance
        disk["path"].extend(path)
        disk["current"] = {"request": req, "started": t, "done_at": t + duration}
        self.log("DISK", req["pid"], "SERVICE",
                 f"{req['op']} {req['path']} at cylinder {req['cylinder']} "
                 f"({self.config.disk_policy}): head {route}, {distance} cylinders, {duration} tick(s)")

    # step 6
    def _remaining(self, pid):
        return self.processes[pid].remaining_work()

    def _should_preempt(self, pcb):
        scheduler = self.config.scheduler
        if scheduler == "Round Robin":
            return self.quantum_used >= self.config.quantum
        if scheduler == "SRTF (preemptive SJF)":
            return min(self._remaining(p) for p in self.ready) < pcb.remaining_work()
        if scheduler == "Priority (preemptive)":
            return min(self.processes[p].priority for p in self.ready) < pcb.priority
        return False  # FCFS, SJF and non-preemptive Priority never preempt

    def _pick_next(self):
        scheduler = self.config.scheduler
        queue = list(self.ready)
        if scheduler in ("SJF (non-preemptive)", "SRTF (preemptive SJF)"):
            return min(queue, key=lambda p: (self._remaining(p), queue.index(p)))
        if scheduler.startswith("Priority"):
            return min(queue, key=lambda p: (self.processes[p].priority, queue.index(p)))
        return queue[0]  # FCFS and Round Robin: front of the queue

    def _schedule(self, t):
        if self.running is not None:
            pcb = self.processes[self.running]
            if self.ready and self._should_preempt(pcb):
                pcb.transition(READY)
                self.ready.append(pcb.pid)
                self.running = None
                self.log("CPU", pcb.pid, "PREEMPT", f"preempted by {self.config.scheduler}")
            elif self.config.scheduler == "Round Robin" and self.quantum_used >= self.config.quantum:
                self.quantum_used = 0  # quantum expired but nobody else is ready: keep running

        if self.running is None and self.ready:
            pid = self._pick_next()
            self.ready.remove(pid)
            pcb = self.processes[pid]
            pcb.transition(RUNNING)
            self.running = pid
            self.quantum_used = 0
            if self.last_ran is not None and self.last_ran != pid:
                self.context_switches += 1
            if pcb.first_run is None:
                pcb.first_run = t
            self.log("CPU", pid, "DISPATCH", f"runs {format_instruction(pcb.current_instruction())}")

    # step 7
    def _execute(self, t):
        if self.running is None:
            return
        pcb = self.processes[self.running]
        self._ran = pcb.pid
        pcb.cpu_time += 1
        self.quantum_used += 1
        op, *args = pcb.current_instruction()

        if op == "CPU":
            pcb.cpu_left -= 1
            if pcb.cpu_left == 0:
                self._instruction_done(pcb, completion_if_last=t + 1)
            return

        if op == "MEM":
            page = args[0]
            if self.memory.access(pcb.pid, page, t):
                frame = self.memory.page_tables[pcb.pid][page]
                self.log("MEMORY", pcb.pid, "HIT", f"page {page} is in frame {frame}")
                self._instruction_done(pcb, completion_if_last=t + 1)
            else:
                pcb.page_faults += 1
                done_at = t + 1 + self.config.page_fault_ticks
                self.page_ins.append({"pid": pcb.pid, "page": page, "done_at": done_at})
                self.log("MEMORY", pcb.pid, "PAGE_FAULT",
                         f"page {page} not resident; page-in will finish at tick {done_at}")
                self._block(pcb, f"page fault on page {page}")
            return

        if op == "REQ":
            resource, count = args
            if self.resources.request(pcb.pid, resource, count):
                self.log("RESOURCE", pcb.pid, "GRANT", f"{resource} x{count} granted")
                self._instruction_done(pcb, completion_if_last=t + 1)
            else:
                self.log("RESOURCE", pcb.pid, "WAIT",
                         f"{resource} x{count} unavailable ({self.resources.available[resource]} free)")
                self._block(pcb, f"waiting for {resource} x{count}")
            return

        if op == "REL":
            resource, count = args
            self.resources.release(pcb.pid, resource, count)
            self.log("RESOURCE", pcb.pid, "RELEASE", f"{resource} x{count} released")
            self._instruction_done(pcb, completion_if_last=t + 1)
            return

        # READ / WRITE: validate now, perform when the disk request completes.
        path = args[0]
        data = args[1] if op == "WRITE" else None
        try:
            if op == "READ":
                if not self.vfs.is_file(path):
                    raise FileSystemError(f"No such file: {path}")
            else:
                self.vfs.check_write(path, data, append=True)
        except FileSystemError as error:
            self.io_errors += 1
            self.log("FILE", pcb.pid, "IO_ERROR", f"{op} {path} failed: {error}")
            self._instruction_done(pcb, completion_if_last=t + 1)
            return
        cylinder = self._cylinder_for(path)
        self.disk["queue"].append({"pid": pcb.pid, "op": op, "path": path, "data": data,
                                   "cylinder": cylinder, "issued": t})
        self.log("DISK", pcb.pid, "REQUEST", f"{op} {path} queued for cylinder {cylinder}")
        self._block(pcb, f"waiting for disk ({op} {path})")

    # step 8
    def _record_tick(self):
        row = {}
        for pid, pcb in self.processes.items():
            state = RUNNING if pid == self._ran else pcb.state
            row[pid] = state
            if state == READY:
                pcb.waiting_time += 1
            elif state == BLOCKED:
                pcb.blocked_time += 1
        self.state_history.append(row)
        self.cpu_timeline.append(self._ran or IDLE)
        if self._ran:
            self.last_ran = self._ran

    # step 9 (runs after the clock has moved to the next tick)
    def active_pids(self):
        return [pid for pid, p in self.processes.items() if p.state != TERMINATED]

    def _check_deadlock(self):
        result = self.resources.detect(self.active_pids())
        found = result["deadlocked"]
        if found and found != self.deadlocked:
            self.log("DEADLOCK", None, "DETECTED",
                     f"deadlock among {', '.join(found)}: " + "; ".join(result["explanation"]))
        self.deadlocked = found
        if found and self.config.auto_recover:
            self.recover_deadlock()

    def recover_deadlock(self):
        """Recovery by process termination: kill victims until no deadlock remains.

        Happens between ticks (at time self.clock). Each victim releases
        everything it holds, then waiting requests are reconsidered immediately.
        Returns the list of victims.
        """
        victims = []
        while True:
            found = self.resources.detect(self.active_pids())["deadlocked"]
            if not found:
                break
            victim = self.resources.pick_victim(found)
            victims.append(victim)
            self.log("DEADLOCK", victim, "RECOVERY",
                     f"terminating {victim} (holds the most resources among {', '.join(found)})")
            self._terminate(self.processes[victim], self.clock, "killed (deadlock recovery)")
        self.deadlocked = []
        if victims:
            self._grant_resources()
        return victims

    # ------------------------------------------------------------ views for the UI and tests

    def counts_by_state(self):
        counts = {s: 0 for s in STATES}
        for p in self.processes.values():
            counts[p.state] += 1
        return counts

    def process_rows(self):
        rows = []
        for pcb in self.processes.values():
            instruction = pcb.current_instruction()
            waiting = self.resources.waiting_for(pcb.pid)
            rows.append({
                "PID": pcb.pid,
                "State": pcb.state,
                "Priority": pcb.priority,
                "Arrival": pcb.arrival,
                "PC": f"{pcb.pc}/{len(pcb.program)}",
                "Current instruction": format_instruction(instruction) if instruction else "-",
                "CPU time": pcb.cpu_time,
                "Waiting": pcb.waiting_time,
                "Blocked": pcb.blocked_time,
                "Page faults": pcb.page_faults,
                "Holds": ", ".join(f"{r} x{c}" for r, c in self.resources.held[pcb.pid].items()) or "-",
                "Waiting for": (pcb.blocked_reason or "-") if not waiting
                               else f"{waiting['resource']} x{waiting['count']}",
                "Response": pcb.response,
                "Completion": pcb.completion,
                "Turnaround": pcb.turnaround,
                "Exit": pcb.exit_reason or "-",
            })
        return rows

    def cpu_segments(self):
        """CPU timeline as Gantt segments [(pid, start, end), ...]."""
        segments = []
        for tick, pid in enumerate(self.cpu_timeline):
            if segments and segments[-1][0] == pid and segments[-1][2] == tick:
                segments[-1] = (pid, segments[-1][1], tick + 1)
            else:
                segments.append((pid, tick, tick + 1))
        return segments

    def metrics(self):
        ticks = self.clock
        busy = sum(1 for pid in self.cpu_timeline if pid != IDLE)
        finished = [p for p in self.processes.values() if p.state == TERMINATED]
        accesses = self.memory.hits + self.memory.faults

        def average(values):
            values = [v for v in values if v is not None]
            return sum(values) / len(values) if values else None

        return {
            "ticks": ticks,
            "cpu_utilization": busy / ticks if ticks else 0.0,
            "throughput": len(finished) / ticks if ticks else 0.0,
            "context_switches": self.context_switches,
            "finished": len(finished),
            "avg_waiting": average(p.waiting_time for p in finished),
            "avg_turnaround": average(p.turnaround for p in finished),
            "avg_response": average(p.response for p in self.processes.values()),
            "page_hits": self.memory.hits,
            "page_faults": self.memory.faults,
            "fault_ratio": self.memory.faults / accesses if accesses else 0.0,
            "disk_movement": self.disk["movement"],
            "disk_completed": self.disk["completed"],
            "io_completed": self.io_completed,
            "io_errors": self.io_errors,
        }

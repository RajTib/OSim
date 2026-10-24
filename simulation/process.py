"""Process control block (PCB), process states and the instruction format.

A simulated process does not run real code. Its "program" is a short list of
instructions (tuples) that the engine executes one tick at a time:

    ("CPU", n)              compute for n ticks
    ("MEM", page)           access one of the process's virtual pages
    ("REQ", resource, n)    request n instances of a shared resource
    ("REL", resource, n)    release n instances
    ("READ", path)          read a file from the virtual file system (disk I/O)
    ("WRITE", path, text)   append text to a file (created if missing; disk I/O)

The process terminates after its last instruction.
"""

NEW = "New"
READY = "Ready"
RUNNING = "Running"
BLOCKED = "Blocked"
TERMINATED = "Terminated"
STATES = [NEW, READY, RUNNING, BLOCKED, TERMINATED]

# Every legal state change. Anything else raises InvalidTransition.
ALLOWED_TRANSITIONS = {
    NEW: {READY},                          # admitted when it arrives
    READY: {RUNNING},                      # dispatched by the scheduler
    RUNNING: {READY, BLOCKED, TERMINATED},  # preempted / waits for something / finishes
    BLOCKED: {READY, TERMINATED},          # wait is over / finishes during the wait or is killed
    TERMINATED: set(),
}

OPCODES = ["CPU", "MEM", "REQ", "REL", "READ", "WRITE"]


class InvalidTransition(ValueError):
    pass


def format_instruction(instruction):
    op, *args = instruction
    if op == "WRITE":
        return f'WRITE {args[0]} "{args[1]}"'
    return " ".join([op] + [str(a) for a in args])


class PCB:
    """Everything the simulated OS knows about one process."""

    def __init__(self, pid, arrival, priority, num_pages, program):
        self.pid = pid
        self.arrival = arrival
        self.priority = priority          # lower number = higher priority
        self.num_pages = num_pages        # size of its virtual address space
        self.program = list(program)
        self.state = NEW
        self.pc = 0                       # index of the current instruction
        self.cpu_left = 0                 # ticks left in the current CPU instruction
        self.cpu_time = 0                 # ticks spent running
        self.waiting_time = 0             # ticks spent in the Ready state
        self.blocked_time = 0             # ticks spent Blocked
        self.first_run = None
        self.completion = None
        self.page_faults = 0
        self.blocked_reason = None        # e.g. "page fault on page 2"
        self.exit_reason = None           # "finished" or "killed (deadlock recovery)"
        self._load_instruction()

    def _load_instruction(self):
        instruction = self.current_instruction()
        if instruction is not None and instruction[0] == "CPU":
            self.cpu_left = instruction[1]

    def transition(self, new_state):
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.pid}: cannot go from {self.state} to {new_state}.")
        self.state = new_state

    def current_instruction(self):
        return self.program[self.pc] if self.pc < len(self.program) else None

    def finish_instruction(self):
        """Move to the next instruction. Returns True if the program is now complete."""
        self.pc += 1
        self._load_instruction()
        return self.pc >= len(self.program)

    def remaining_work(self):
        """Estimated ticks of work left, used by SJF/SRTF in the simulation.

        CPU instructions count their remaining ticks; every other instruction
        counts as 1 tick. (A real OS cannot know this; the simulator can.)
        """
        total = 0
        for i in range(self.pc, len(self.program)):
            op = self.program[i][0]
            if op == "CPU":
                total += self.cpu_left if i == self.pc else self.program[i][1]
            else:
                total += 1
        return total

    @property
    def turnaround(self):
        return None if self.completion is None else self.completion - self.arrival

    @property
    def response(self):
        return None if self.first_run is None else self.first_run - self.arrival

"""Tests for the integrated simulation (PCBs, paging, resources, file I/O, engine).

Expected tick-by-tick behaviour was traced by hand using the tick order
documented at the top of simulation/engine.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.cpu_scheduling import run_algorithm
from simulation.engine import SimConfig, Simulation
from simulation.memory import PagedMemory
from simulation.process import BLOCKED, NEW, PCB, READY, RUNNING, TERMINATED, InvalidTransition
from simulation.scenarios import SCENARIOS, build_scenario, build_simulation
from simulation.workload import parse_workload, validate_workload


def make(workload, resources="printer=1", files="", **config):
    config.setdefault("scheduler", "FCFS")
    return build_simulation(workload, resources, files, **config)


def events(sim, event=None, pid=None):
    return [e for e in sim.events
            if (event is None or e["event"] == event) and (pid is None or e["pid"] == pid)]


def history(sim, pid):
    return [row[pid] for row in sim.state_history]


# ---------------------------------------------------------------- PCB and states

def test_pcb_valid_lifecycle():
    pcb = PCB("P1", 0, 1, 1, [("CPU", 1)])
    for state in (READY, RUNNING, BLOCKED, READY, RUNNING, TERMINATED):
        pcb.transition(state)
    assert pcb.state == TERMINATED


@pytest.mark.parametrize("path", [
    [RUNNING],                    # New -> Running (must be admitted first)
    [READY, BLOCKED],             # Ready -> Blocked (only a running process can block)
    [READY, RUNNING, BLOCKED, RUNNING],  # Blocked -> Running (must go through Ready)
    [READY, RUNNING, TERMINATED, READY],  # Terminated is final
])
def test_pcb_invalid_transitions(path):
    pcb = PCB("P1", 0, 1, 1, [("CPU", 1)])
    with pytest.raises(InvalidTransition):
        for state in path:
            pcb.transition(state)


def test_remaining_work_estimate():
    pcb = PCB("P1", 0, 1, 2, [("CPU", 3), ("MEM", 0), ("CPU", 2)])
    assert pcb.remaining_work() == 6  # 3 + 1 + 2
    pcb.cpu_left -= 1
    assert pcb.remaining_work() == 5


# ---------------------------------------------------------------- paged memory

def test_page_table_fault_load_hit():
    memory = PagedMemory(2)
    memory.add_process("A", 3)

    assert memory.access("A", 1, tick=0) is False      # fault
    assert memory.load("A", 1, tick=2) == (0, None)    # free frame 0
    assert memory.page_tables["A"] == {1: 0}
    assert memory.access("A", 1, tick=3) is True       # hit
    assert (memory.hits, memory.faults) == (1, 1)


@pytest.mark.parametrize("policy, victim", [("FIFO", ("A", 0)), ("LRU", ("B", 0))])
def test_global_replacement_updates_victim_page_table(policy, victim):
    # Frames: A0 loaded at t0, B0 at t1; A0 used again at t2. Loading B1 at t3:
    # FIFO evicts A0 (loaded first); LRU evicts B0 (A0 was used more recently).
    memory = PagedMemory(2, policy)
    memory.add_process("A", 1)
    memory.add_process("B", 2)
    memory.load("A", 0, 0)
    memory.load("B", 0, 1)
    memory.access("A", 0, 2)

    frame, evicted = memory.load("B", 1, 3)

    assert evicted == victim
    assert not memory.is_resident(*victim)
    assert memory.page_tables["B"][1] == frame


def test_free_process_releases_frames():
    memory = PagedMemory(3)
    memory.add_process("A", 2)
    memory.load("A", 0, 0)
    memory.load("A", 1, 0)

    assert memory.free_process("A") == [0, 1]
    assert memory.used_frames() == 0 and memory.page_tables["A"] == {}


def test_memory_rejects_optimal_and_bad_pages():
    with pytest.raises(ValueError, match="FIFO or LRU"):
        PagedMemory(3, "Optimal")
    memory = PagedMemory(3)
    memory.add_process("A", 2)
    with pytest.raises(ValueError, match="outside"):
        memory.access("A", 5, 0)


# ---------------------------------------------------------------- CPU scheduling in the engine

def test_single_cpu_process():
    sim = make("P1 0 0 1 : CPU 3")
    sim.run()

    assert sim.cpu_timeline == ["P1", "P1", "P1"]
    assert sim.processes["P1"].completion == 3
    assert sim.status == "finished"


def test_idle_cpu_before_arrival():
    sim = make("P1 2 0 1 : CPU 1")
    sim.run()

    assert sim.cpu_timeline == ["Idle", "Idle", "P1"]
    assert history(sim, "P1") == [NEW, NEW, RUNNING]
    assert sim.processes["P1"].response == 0


def expand(timeline):
    ticks = []
    for pid, start, end in timeline:
        ticks += [pid] * (end - start)
    return ticks


def P(pid, arrival, burst, priority=0):
    return {"pid": pid, "arrival": arrival, "burst": burst, "priority": priority}


RR_WORKLOAD = [P("P1", 0, 5), P("P2", 1, 3), P("P3", 2, 1), P("P4", 3, 2), P("P5", 4, 3)]
CLASSIC = [P("P1", 0, 8), P("P2", 1, 4), P("P3", 2, 9), P("P4", 3, 5)]
PRIORITY = [P("P1", 0, 10, 3), P("P2", 0, 1, 1), P("P3", 0, 2, 4), P("P4", 0, 1, 5), P("P5", 0, 5, 2)]


@pytest.mark.parametrize("scheduler, workload", [
    ("FCFS", RR_WORKLOAD),
    ("Round Robin", RR_WORKLOAD),
    ("SJF (non-preemptive)", CLASSIC),
    ("SRTF (preemptive SJF)", CLASSIC),
    ("Priority (non-preemptive)", PRIORITY),
    ("Priority (preemptive)", [P("P1", 0, 4, 3), P("P2", 1, 2, 1)]),
])
def test_engine_matches_standalone_scheduler_for_cpu_only_work(scheduler, workload):
    # With only CPU instructions, the tick-by-tick engine must make exactly the
    # same decisions as the standalone algorithm (already checked by hand in
    # test_cpu_scheduling.py).
    text = "\n".join(f"{p['pid']} {p['arrival']} {p['priority']} 1 : CPU {p['burst']}" for p in workload)
    sim = make(text, scheduler=scheduler, quantum=2)
    sim.run()
    expected = run_algorithm(scheduler, workload, 2)

    assert sim.cpu_timeline == expand(expected["timeline"])
    assert {pid: p.completion for pid, p in sim.processes.items()} == \
        {r["pid"]: r["completion"] for r in expected["processes"]}
    assert {pid: p.waiting_time for pid, p in sim.processes.items()} == \
        {r["pid"]: r["waiting"] for r in expected["processes"]}


# ---------------------------------------------------------------- page faults

def test_page_fault_blocks_and_page_in_resumes():
    # t0: MEM 0 faults (page-in done at 0 + 1 + 2 = 3); t1, t2 blocked (CPU idle);
    # t3: page-in completes -> Ready -> dispatched -> CPU 1 -> finishes at 4.
    sim = make("P1 0 0 2 : MEM 0; CPU 1", page_fault_ticks=2)
    sim.run()

    assert history(sim, "P1") == [RUNNING, BLOCKED, BLOCKED, RUNNING]
    assert sim.cpu_timeline == ["P1", "Idle", "Idle", "P1"]
    assert sim.processes["P1"].completion == 4
    assert sim.processes["P1"].page_faults == 1
    assert [(e["tick"], e["event"]) for e in sim.events if e["subsystem"] == "MEMORY"] == \
        [(0, "PAGE_FAULT"), (3, "PAGE_IN")]
    assert events(sim, "WAKE", "P1")[0]["tick"] == 3


def test_page_table_updated_and_second_access_hits():
    # t0 fault, t3 page-in + second MEM 0 hits, t4 CPU 1 -> completion 5.
    sim = make("P1 0 0 2 : MEM 0; MEM 0; CPU 1", page_fault_ticks=2)
    for _ in range(3):
        sim.step()
    assert sim.memory.page_tables["P1"] == {}  # page-in still pending
    sim.step()
    assert sim.memory.page_tables["P1"] == {0: 0}

    sim.run()
    assert (sim.memory.hits, sim.memory.faults) == (1, 1)
    assert sim.processes["P1"].completion == 5
    assert [e["tick"] for e in events(sim, "HIT")] == [3]
    assert sim.memory.page_tables["P1"] == {}  # frames are freed when the process exits


def test_other_process_runs_while_one_waits_for_page_in():
    # FCFS: P1 faults at t0; P2 runs t1-t3; P1 is ready at t3 but must wait for P2 (FCFS).
    sim = make("P1 0 0 1 : MEM 0; CPU 1\nP2 0 0 1 : CPU 3", page_fault_ticks=2)
    sim.run()

    assert sim.cpu_timeline == ["P1", "P2", "P2", "P2", "P1"]
    assert sim.processes["P2"].completion == 4
    assert sim.processes["P1"].completion == 5


def test_page_in_evicts_another_process_page():
    # 1 frame. t0 P1 faults (done t2), t1 P2 faults (done t3), t2 P1 page 0 -> frame 0,
    # t3 P2's page-in evicts P1's page 0 (FIFO).
    sim = make("P1 0 0 1 : MEM 0; CPU 5\nP2 0 0 1 : MEM 0; CPU 1", num_frames=1, page_fault_ticks=1)
    for _ in range(4):
        sim.step()

    assert sim.memory.page_tables == {"P1": {}, "P2": {0: 0}}
    evict = events(sim, "EVICT")
    assert len(evict) == 1 and evict[0]["pid"] == "P1" and evict[0]["tick"] == 3


# ---------------------------------------------------------------- resources

def test_resource_request_blocks_until_release():
    # Round Robin q=1. t0 P1 gets the printer. t1 P2 asks -> blocked.
    # P1 runs t2, t3 (CPU 2) and releases at t4 (finishes, completion 5).
    # t5: P2's waiting request is granted -> Ready -> runs CPU 1; t6 releases -> done at 7.
    sim = make("P1 0 1 1 : REQ printer 1; CPU 2; REL printer 1\n"
               "P2 0 1 1 : REQ printer 1; CPU 1; REL printer 1", scheduler="Round Robin", quantum=1)
    sim.run()

    assert sim.cpu_timeline == ["P1", "P2", "P1", "P1", "P1", "P2", "P2"]
    assert history(sim, "P2") == [READY, RUNNING, BLOCKED, BLOCKED, BLOCKED, RUNNING, RUNNING]
    assert sim.processes["P1"].completion == 5
    assert sim.processes["P2"].completion == 7
    assert sim.processes["P2"].blocked_time == 3
    assert [e["tick"] for e in events(sim, "WAIT")] == [1]
    assert [e["tick"] for e in events(sim, "GRANT", "P2")] == [5]


def test_resources_released_when_process_exits():
    # P1 never releases the printer; it is released automatically at exit (end of t3),
    # and P2 gets it at t4.
    sim = make("P1 0 1 1 : REQ printer 1; CPU 2\nP2 0 1 1 : REQ printer 1; CPU 1",
               scheduler="Round Robin", quantum=1)
    sim.run()

    exit_details = events(sim, "EXIT", "P1")[0]["details"]
    assert "released printer x1" in exit_details
    assert sim.processes["P2"].completion == 5
    sim.resources.check_invariants()


# ---------------------------------------------------------------- file I/O and disk

def test_file_read_blocks_until_disk_completes():
    # t0 READ issued (blocked). t1 disk starts: distance 0 -> 1 tick. t2 READ_DONE -> Ready -> CPU.
    sim = make("P1 0 0 1 : READ /f.txt; CPU 1", files="/f.txt = abc", disk_head=0)
    sim.run()

    assert sim.cpu_timeline == ["P1", "Idle", "P1"]
    assert sim.processes["P1"].completion == 3
    assert [(e["tick"], e["event"]) for e in sim.events if e["subsystem"] in ("DISK", "FILE")] == \
        [(0, "REQUEST"), (1, "SERVICE"), (2, "READ_DONE"), (2, "DONE")]


def test_disk_service_time_depends_on_seek_distance():
    # 4 blocks over 200 cylinders: /b is block 1 -> cylinder 50. Head at 0, 25 cylinders per tick:
    # service = 1 + ceil(50 / 25) = 3 ticks: starts t1, done t4.
    sim = make("P1 0 0 1 : READ /b; CPU 1", files="/a = x\n/b = y",
               disk_blocks=4, disk_head=0, seek_rate=25)
    sim.run()

    assert sim.processes["P1"].completion == 5
    assert sim.disk["movement"] == 50
    assert sim.disk["head"] == 50


def test_write_creates_then_appends_file():
    sim = make("P1 0 0 1 : WRITE /logs/out.txt hello there; WRITE /logs/out.txt !",
               files="/logs/old.txt = x")
    sim.run()

    assert sim.vfs.read_file("/logs/out.txt") == "hello there!"
    assert sim.vfs.file_blocks("/logs/out.txt") == [1]  # block 0 belongs to old.txt
    assert len(events(sim, "WRITE_DONE")) == 2
    assert sim.io_completed == 2


def test_failed_file_operation_does_not_block():
    sim = make("P1 0 0 1 : READ /missing.txt; CPU 1")
    sim.run()

    assert sim.cpu_timeline == ["P1", "P1"]
    assert BLOCKED not in history(sim, "P1")
    assert sim.io_errors == 1
    assert "No such file" in events(sim, "IO_ERROR")[0]["details"]


DISK_FILES = "/a = x\n/p1 = " + "x" * 99 + "\n/b = x\n/p2 = " + "x" * 89 + "\n/c = x"
DISK_WORK = "P1 0 0 1 : READ /c\nP2 0 0 1 : READ /a\nP3 0 0 1 : READ /b"


@pytest.mark.parametrize("policy, order, movement", [
    # Block = cylinder here. Head 95. /c (190) is serviced first because it is alone in
    # the queue; then /a (0) and /b (100) are both waiting at cylinder 190.
    ("FCFS", ["/c", "/a", "/b"], 95 + 190 + 100),
    ("SSTF", ["/c", "/b", "/a"], 95 + 90 + 100),
])
def test_disk_policy_controls_service_order(policy, order, movement):
    sim = make(DISK_WORK, files=DISK_FILES, disk_policy=policy, disk_blocks=200,
               block_size=1, disk_head=95, seek_rate=200)
    sim.run()

    served = [e["details"].split()[1] for e in events(sim, "SERVICE")]
    assert served == order
    assert sim.disk["movement"] == movement
    assert sim.status == "finished"


# ---------------------------------------------------------------- deadlock in the engine

def test_deadlock_detected_and_simulation_does_not_hang():
    sim = build_scenario("Deadlock and recovery")
    ticks = sim.run(max_ticks=500)

    assert ticks < 500                 # run() stops by itself
    assert sim.status == "deadlocked"
    assert sim.deadlocked == ["P1", "P2"]
    assert sim.can_progress() is False
    assert sim.processes["P3"].state == TERMINATED  # the unrelated process still finished
    detail = events(sim, "DETECTED")[0]["details"]
    assert "P1 holds A x1 and waits for B x1 (held by P2)" in detail


def test_manual_deadlock_recovery():
    sim = build_scenario("Deadlock and recovery")
    sim.run()

    assert sim.recover_deadlock() == ["P1"]
    assert sim.processes["P1"].exit_reason == "killed (deadlock recovery)"
    sim.run()
    assert sim.status == "finished"
    assert sim.processes["P2"].exit_reason == "finished"
    sim.resources.check_invariants()


def test_automatic_deadlock_recovery():
    sim = build_scenario("Deadlock and recovery", auto_recover=True)
    sim.run()

    assert sim.status == "finished"
    assert len(events(sim, "RECOVERY")) == 1


# ---------------------------------------------------------------- engine-wide properties

def test_step_advances_existing_state_by_one_tick():
    sim = build_scenario("All subsystems together")
    sim.step()
    sim.step()
    assert sim.clock == 2 and len(sim.state_history) == 2

    sim.run()
    clock = sim.clock
    assert sim.step() is False  # finished: nothing more happens
    assert sim.clock == clock


def test_reset_and_repeated_runs_are_deterministic():
    first = build_scenario("All subsystems together")
    first.run()
    second = build_scenario("All subsystems together")
    second.run()

    assert first.events == second.events
    assert first.cpu_timeline == second.cpu_timeline


def test_all_subsystems_scenario_really_interacts():
    sim = build_scenario("All subsystems together")
    sim.run()

    seen = {(e["subsystem"], e["event"]) for e in sim.events}
    for expected in [("MEMORY", "PAGE_FAULT"), ("MEMORY", "PAGE_IN"), ("MEMORY", "EVICT"),
                     ("RESOURCE", "WAIT"), ("RESOURCE", "GRANT"), ("DISK", "REQUEST"),
                     ("DISK", "SERVICE"), ("FILE", "READ_DONE"), ("FILE", "WRITE_DONE"),
                     ("CPU", "PREEMPT"), ("PROCESS", "BLOCK"), ("PROCESS", "WAKE")]:
        assert expected in seen
    assert sim.vfs.read_file("/logs/app.log") == "boot ok;P4 finished"
    assert sim.status == "finished"


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_invariants_hold_on_every_tick(name):
    sim = build_scenario(name, auto_recover=True)
    while sim.can_progress() and sim.clock < 300:
        sim.step()
        sim.resources.check_invariants()
        # page tables and frames agree
        for f, content in enumerate(sim.memory.frames):
            if content:
                assert sim.memory.page_tables[content["pid"]][content["page"]] == f
        # each process is in exactly the right place for its state
        for pid, pcb in sim.processes.items():
            assert (pid in sim.ready) == (pcb.state == READY)
            assert (sim.running == pid) == (pcb.state == RUNNING)
            if pcb.state == BLOCKED:
                waiting_resource = sim.resources.waiting_for(pid) is not None
                waiting_page = any(op["pid"] == pid for op in sim.page_ins)
                waiting_disk = any(r["pid"] == pid for r in sim.disk["queue"]) or (
                    sim.disk["current"] and sim.disk["current"]["request"]["pid"] == pid)
                assert waiting_resource or waiting_page or waiting_disk
    assert sim.status == "finished"


def test_event_log_format():
    sim = build_scenario("All subsystems together")
    sim.run()

    ticks = [e["tick"] for e in sim.events]
    assert ticks == sorted(ticks)
    for e in sim.events:
        assert set(e) == {"tick", "subsystem", "pid", "event", "details"}
        assert e["subsystem"] in {"SYSTEM", "PROCESS", "CPU", "MEMORY", "RESOURCE",
                                  "DEADLOCK", "DISK", "FILE"}


def test_metrics_come_from_the_run():
    sim = make("P1 1 0 1 : CPU 2")
    sim.run()
    m = sim.metrics()

    assert m["ticks"] == 3
    assert m["cpu_utilization"] == pytest.approx(2 / 3)
    assert m["finished"] == 1 and m["avg_turnaround"] == 2


# ---------------------------------------------------------------- invalid input

@pytest.mark.parametrize("text", [
    "P1 0 0 1 CPU 2",                 # missing ':'
    "P1 0 0 : CPU 2",                 # missing a header field
    "P1 0 0 1 : JUMP 3",              # unknown instruction
    "P1 x 0 1 : CPU 2",               # arrival not a number
    "P1 0 0 1 : REQ printer",         # missing count
    "P1 0 0 1 : WRITE /a",            # missing text
])
def test_workload_parse_errors(text):
    with pytest.raises(ValueError):
        parse_workload(text)


@pytest.mark.parametrize("text, message", [
    ("P1 0 0 1 : REQ printer 2", "only 1 exist"),
    ("P1 0 0 1 : REQ printer 1; REQ printer 1", "only 1 exist"),
    ("P1 0 0 1 : REL printer 1", "holds only 0"),
    ("P1 0 0 1 : REQ scanner 1", "unknown resource"),
    ("P1 0 0 2 : MEM 2", "outside pages"),
    ("P1 0 0 1 : CPU 0", "greater than 0"),
    ("P1 0 0 1 : READ data.txt", "absolute"),
    ("P1 0 0 1 : CPU 1\nP1 1 0 1 : CPU 1", "Duplicate"),
])
def test_workload_validation_errors(text, message):
    with pytest.raises(ValueError, match=message):
        validate_workload(parse_workload(text), {"printer": 1})


@pytest.mark.parametrize("bad", [
    {"page_policy": "Optimal"}, {"quantum": 0}, {"num_frames": 0},
    {"disk_head": 500}, {"scheduler": "Lottery"}, {"disk_policy": "ELEVATOR"},
])
def test_invalid_configuration(bad):
    with pytest.raises(ValueError):
        Simulation(SimConfig(**bad), parse_workload("P1 0 0 1 : CPU 1"))

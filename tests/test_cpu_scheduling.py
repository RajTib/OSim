"""Tests for FCFS and Round Robin.

Expected values were worked out by hand (the working is in each comment),
not copied from the program's output.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.cpu_scheduling import (compare_algorithms, fcfs, priority_scheduling, round_robin,
                                       run_algorithm, sjf, srtf)


def proc(pid, arrival, burst):
    return {"pid": pid, "arrival": arrival, "burst": burst}


def by_pid(result):
    return {row["pid"]: row for row in result["processes"]}


# ---------------------------------------------------------------- FCFS

def test_fcfs_different_arrival_times():
    # P1 runs 0-5, P2 runs 5-8, P3 runs 8-16
    # P1: CT=5,  TAT=5-0=5,   WT=5-5=0
    # P2: CT=8,  TAT=8-1=7,   WT=7-3=4
    # P3: CT=16, TAT=16-2=14, WT=14-8=6
    result = fcfs([proc("P1", 0, 5), proc("P2", 1, 3), proc("P3", 2, 8)])

    assert result["timeline"] == [("P1", 0, 5), ("P2", 5, 8), ("P3", 8, 16)]
    rows = by_pid(result)
    assert (rows["P1"]["completion"], rows["P1"]["turnaround"], rows["P1"]["waiting"]) == (5, 5, 0)
    assert (rows["P2"]["completion"], rows["P2"]["turnaround"], rows["P2"]["waiting"]) == (8, 7, 4)
    assert (rows["P3"]["completion"], rows["P3"]["turnaround"], rows["P3"]["waiting"]) == (16, 14, 6)
    assert result["avg_waiting"] == pytest.approx(10 / 3)
    assert result["avg_turnaround"] == pytest.approx(26 / 3)


def test_fcfs_orders_by_arrival_not_input_order():
    # Given out of order, P2 (arrives at 0) must still go first.
    result = fcfs([proc("P1", 4, 2), proc("P2", 0, 3)])

    assert result["timeline"] == [("P2", 0, 3), ("Idle", 3, 4), ("P1", 4, 6)]


def test_fcfs_idle_at_start():
    # CPU idle 0-3, then P1 runs 3-7.  TAT=7-3=4, WT=0.
    result = fcfs([proc("P1", 3, 4)])

    assert result["timeline"] == [("Idle", 0, 3), ("P1", 3, 7)]
    row = by_pid(result)["P1"]
    assert (row["completion"], row["turnaround"], row["waiting"]) == (7, 4, 0)


def test_fcfs_idle_between_processes():
    # P1 runs 2-5, CPU idle 5-10, P2 runs 10-12.  Nobody ever waits.
    result = fcfs([proc("P1", 2, 3), proc("P2", 10, 2)])

    assert result["timeline"] == [
        ("Idle", 0, 2), ("P1", 2, 5), ("Idle", 5, 10), ("P2", 10, 12),
    ]
    rows = by_pid(result)
    assert rows["P1"]["waiting"] == 0 and rows["P2"]["waiting"] == 0
    assert rows["P2"]["turnaround"] == 2


def test_fcfs_same_arrival_keeps_input_order():
    result = fcfs([proc("B", 0, 2), proc("A", 0, 2)])

    assert [seg[0] for seg in result["timeline"]] == ["B", "A"]


# ---------------------------------------------------------- Round Robin

def test_round_robin_multiple_processes_different_arrivals():
    # Quantum 2. Ready queue after each slice (new arrivals join before the
    # preempted process):
    #   P1 0-2 (rem 3)  queue: P2 P3 P1
    #   P2 2-4 (rem 1)  queue: P3 P1 P4 P5 P2
    #   P3 4-5 done     queue: P1 P4 P5 P2
    #   P1 5-7 (rem 1)  queue: P4 P5 P2 P1
    #   P4 7-9 done     queue: P5 P2 P1
    #   P5 9-11 (rem 1) queue: P2 P1 P5
    #   P2 11-12 done, P1 12-13 done, P5 13-14 done
    procs = [
        proc("P1", 0, 5), proc("P2", 1, 3), proc("P3", 2, 1),
        proc("P4", 3, 2), proc("P5", 4, 3),
    ]
    result = round_robin(procs, 2)

    assert result["timeline"] == [
        ("P1", 0, 2), ("P2", 2, 4), ("P3", 4, 5), ("P1", 5, 7), ("P4", 7, 9),
        ("P5", 9, 11), ("P2", 11, 12), ("P1", 12, 13), ("P5", 13, 14),
    ]
    rows = by_pid(result)
    assert {k: v["completion"] for k, v in rows.items()} == {
        "P1": 13, "P2": 12, "P3": 5, "P4": 9, "P5": 14,
    }
    # TAT = CT - arrival: 13, 11, 3, 6, 10      WT = TAT - burst: 8, 8, 2, 4, 7
    assert {k: v["turnaround"] for k, v in rows.items()} == {
        "P1": 13, "P2": 11, "P3": 3, "P4": 6, "P5": 10,
    }
    assert {k: v["waiting"] for k, v in rows.items()} == {
        "P1": 8, "P2": 8, "P3": 2, "P4": 4, "P5": 7,
    }
    assert result["avg_turnaround"] == pytest.approx(43 / 5)
    assert result["avg_waiting"] == pytest.approx(29 / 5)


def test_round_robin_single_process_is_split_into_quantum_slices():
    # Burst 5, quantum 2 -> slices of 2, 2, 1. Nobody else exists, so WT=0.
    result = round_robin([proc("P1", 0, 5)], 2)

    assert result["timeline"] == [("P1", 0, 2), ("P1", 2, 4), ("P1", 4, 5)]
    row = by_pid(result)["P1"]
    assert (row["completion"], row["turnaround"], row["waiting"]) == (5, 5, 0)


def test_round_robin_cpu_idle_between_processes():
    # P1 finishes at 2, P2 only arrives at 5 -> CPU idle 2-5.
    result = round_robin([proc("P1", 0, 2), proc("P2", 5, 2)], 3)

    assert result["timeline"] == [("P1", 0, 2), ("Idle", 2, 5), ("P2", 5, 7)]
    assert by_pid(result)["P2"]["waiting"] == 0


def test_round_robin_cpu_idle_at_start():
    result = round_robin([proc("P1", 4, 3)], 5)

    assert result["timeline"] == [("Idle", 0, 4), ("P1", 4, 7)]


def test_round_robin_arrival_is_queued_before_preempted_process():
    # P2 arrives at t=2, exactly when P1's first quantum ends.
    # P2 must go ahead of P1, so P2 runs 2-4 and P1 finishes 4-6.
    result = round_robin([proc("P1", 0, 4), proc("P2", 2, 2)], 2)

    assert result["timeline"] == [("P1", 0, 2), ("P2", 2, 4), ("P1", 4, 6)]
    rows = by_pid(result)
    assert rows["P2"]["completion"] == 4 and rows["P2"]["waiting"] == 0
    assert rows["P1"]["completion"] == 6 and rows["P1"]["waiting"] == 2


def test_round_robin_with_huge_quantum_behaves_like_fcfs():
    procs = [proc("P1", 0, 5), proc("P2", 1, 3), proc("P3", 2, 8)]

    assert round_robin(procs, 100)["timeline"] == fcfs(procs)["timeline"]


def test_timeline_is_continuous():
    # Every segment must start exactly where the previous one ended.
    result = round_robin([proc("A", 0, 3), proc("B", 8, 2), proc("C", 9, 4)], 2)

    timeline = result["timeline"]
    assert timeline[0][1] == 0
    for (_, _, prev_end), (_, next_start, _) in zip(timeline, timeline[1:]):
        assert prev_end == next_start


# --------------------------------------------------- invalid input

@pytest.mark.parametrize("algorithm", [
    fcfs,
    lambda procs: round_robin(procs, 2),
], ids=["fcfs", "round_robin"])
class TestInvalidProcesses:
    def test_negative_arrival(self, algorithm):
        with pytest.raises(ValueError, match="arrival"):
            algorithm([proc("P1", -1, 3)])

    def test_zero_burst(self, algorithm):
        with pytest.raises(ValueError, match="burst"):
            algorithm([proc("P1", 0, 0)])

    def test_negative_burst(self, algorithm):
        with pytest.raises(ValueError, match="burst"):
            algorithm([proc("P1", 0, -4)])

    def test_empty_process_list(self, algorithm):
        with pytest.raises(ValueError):
            algorithm([])

    def test_duplicate_pid(self, algorithm):
        with pytest.raises(ValueError, match="Duplicate"):
            algorithm([proc("P1", 0, 3), proc("P1", 1, 2)])

    def test_non_integer_burst(self, algorithm):
        with pytest.raises(ValueError, match="burst"):
            algorithm([proc("P1", 0, 2.5)])


@pytest.mark.parametrize("quantum", [0, -1, 1.5, "2", True])
def test_round_robin_invalid_time_quantum(quantum):
    with pytest.raises(ValueError, match="quantum"):
        round_robin([proc("P1", 0, 3)], quantum)


# ------------------------------------------------- SJF, SRTF and Priority

def pproc(pid, arrival, burst, priority):
    return {"pid": pid, "arrival": arrival, "burst": burst, "priority": priority}


# Classic textbook workload (Silberschatz): P1(0,8) P2(1,4) P3(2,9) P4(3,5)
CLASSIC = [proc("P1", 0, 8), proc("P2", 1, 4), proc("P3", 2, 9), proc("P4", 3, 5)]


def test_sjf_classic_example():
    # P1 runs first (only one there), then shortest of P2(4), P3(9), P4(5): P2, P4, P3.
    # WT: P1 0, P2 8-1=7, P4 12-3=9, P3 17-2=15  -> 31/4
    result = sjf(CLASSIC)

    assert result["timeline"] == [("P1", 0, 8), ("P2", 8, 12), ("P4", 12, 17), ("P3", 17, 26)]
    assert {r["pid"]: r["waiting"] for r in result["processes"]} == {"P1": 0, "P2": 7, "P3": 15, "P4": 9}
    assert result["avg_waiting"] == pytest.approx(7.75)


def test_sjf_ties_use_arrival_then_input_order():
    # At t=4 both B (arrived 1) and C (arrived 2) have burst 2 -> B first.
    # D and E arrive together with equal bursts -> input order (D first).
    result = sjf([proc("A", 0, 4), proc("C", 2, 2), proc("B", 1, 2), proc("D", 20, 1), proc("E", 20, 1)])

    assert [s[0] for s in result["timeline"]] == ["A", "B", "C", "Idle", "D", "E"]


def test_sjf_idle_gap():
    result = sjf([proc("P1", 3, 2)])

    assert result["timeline"] == [("Idle", 0, 3), ("P1", 3, 5)]


def test_srtf_classic_example():
    # t=1: P2 (4) < P1 remaining (7) -> preempt. P2 finishes at 5.
    # Then P4 (5) < P1 (7) < P3 (9): P4 5-10, P1 10-17, P3 17-26.
    # WT: P1 17-0-8=9, P2 0, P3 26-2-9=15, P4 10-3-5=2 -> 26/4 = 6.5
    result = srtf(CLASSIC)

    assert result["timeline"] == [
        ("P1", 0, 1), ("P2", 1, 5), ("P4", 5, 10), ("P1", 10, 17), ("P3", 17, 26),
    ]
    assert result["avg_waiting"] == pytest.approx(6.5)
    assert result["context_switches"] == 4


def test_srtf_equal_remaining_time_does_not_preempt():
    # At t=1, P1 has 3 left and P2 needs 3: equal, so P1 keeps the CPU.
    result = srtf([proc("P1", 0, 4), proc("P2", 1, 3)])

    assert result["timeline"] == [("P1", 0, 4), ("P2", 4, 7)]


def test_priority_non_preemptive_classic_example():
    # Silberschatz: all arrive at 0; (burst, priority) P1(10,3) P2(1,1) P3(2,4) P4(1,5) P5(5,2)
    # Order by priority: P2, P5, P1, P3, P4.  WT: 6, 0, 16, 18, 1 -> 41/5 = 8.2
    workload = [pproc("P1", 0, 10, 3), pproc("P2", 0, 1, 1), pproc("P3", 0, 2, 4),
                pproc("P4", 0, 1, 5), pproc("P5", 0, 5, 2)]
    result = priority_scheduling(workload)

    assert result["timeline"] == [("P2", 0, 1), ("P5", 1, 6), ("P1", 6, 16), ("P3", 16, 18), ("P4", 18, 19)]
    assert result["avg_waiting"] == pytest.approx(8.2)


def test_priority_non_preemptive_does_not_interrupt():
    # P2 has a higher priority but arrives while P1 runs: it waits.
    result = priority_scheduling([pproc("P1", 0, 4, 3), pproc("P2", 1, 2, 1)])

    assert result["timeline"] == [("P1", 0, 4), ("P2", 4, 6)]


def test_priority_preemptive_interrupts_for_higher_priority():
    # P2 (priority 1) arrives at 1 and preempts P1 (priority 3); P1 resumes at 3.
    result = priority_scheduling([pproc("P1", 0, 4, 3), pproc("P2", 1, 2, 1)], preemptive=True)

    assert result["timeline"] == [("P1", 0, 1), ("P2", 1, 3), ("P1", 3, 6)]
    rows = by_pid(result)
    assert rows["P1"]["waiting"] == 2 and rows["P2"]["waiting"] == 0


def test_priority_preemptive_equal_priority_does_not_preempt():
    result = priority_scheduling([pproc("P1", 0, 3, 2), pproc("P2", 1, 2, 2)], preemptive=True)

    assert result["timeline"] == [("P1", 0, 3), ("P2", 3, 5)]


# ------------------------------------------------- extra metrics

def test_response_time_round_robin():
    # From the 5-process Round Robin example above: first runs at 0, 2, 4, 7, 9.
    procs = [proc("P1", 0, 5), proc("P2", 1, 3), proc("P3", 2, 1), proc("P4", 3, 2), proc("P5", 4, 3)]
    result = round_robin(procs, 2)

    assert {r["pid"]: r["response"] for r in result["processes"]} == {
        "P1": 0, "P2": 1, "P3": 2, "P4": 4, "P5": 5,
    }
    # Timeline P1 P2 P3 P1 P4 P5 P2 P1 P5: every neighbour differs -> 8 switches.
    assert result["context_switches"] == 8


def test_cpu_utilization_and_throughput_include_idle_time():
    # Busy 2-5 and 10-12 = 5 units out of 12; 2 processes in 12 units.
    result = fcfs([proc("P1", 2, 3), proc("P2", 10, 2)])

    assert result["cpu_utilization"] == pytest.approx(5 / 12)
    assert result["throughput"] == pytest.approx(2 / 12)
    assert result["total_time"] == 12
    assert result["context_switches"] == 1


def test_single_process_has_no_context_switches():
    assert round_robin([proc("P1", 0, 5)], 2)["context_switches"] == 0


def test_compare_algorithms_on_same_workload():
    # FCFS on CLASSIC: P1 0-8, P2 8-12, P3 12-21, P4 21-26 -> WT 0+7+10+18 = 35/4
    rows = {r["algorithm"]: r for r in compare_algorithms(CLASSIC, 2)}

    assert len(rows) == 6
    assert rows["FCFS"]["avg_waiting"] == pytest.approx(8.75)
    assert rows["SJF (non-preemptive)"]["avg_waiting"] == pytest.approx(7.75)
    assert rows["SRTF (preemptive SJF)"]["avg_waiting"] == pytest.approx(6.5)


def test_negative_priority_is_rejected():
    with pytest.raises(ValueError, match="priority"):
        sjf([pproc("P1", 0, 3, -1)])


def test_unknown_algorithm_name():
    with pytest.raises(ValueError, match="Unknown"):
        run_algorithm("Lottery", [proc("P1", 0, 1)])


@pytest.mark.parametrize("algorithm", [sjf, srtf, priority_scheduling],
                         ids=["sjf", "srtf", "priority"])
def test_new_algorithms_reject_invalid_processes(algorithm):
    with pytest.raises(ValueError, match="arrival"):
        algorithm([proc("P1", -1, 3)])
    with pytest.raises(ValueError, match="burst"):
        algorithm([proc("P1", 0, 0)])

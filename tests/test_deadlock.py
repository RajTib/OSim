"""Tests for deadlock detection, recovery, Banker's algorithm and the resource manager.

Matrix examples are the standard Silberschatz ones (5 processes, resources A, B, C).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.deadlock import (bankers_request, bankers_safety, detect_deadlock,
                                 explain_deadlock, recover_by_termination)
from simulation.resources import ResourceManager, parse_resources

# Banker's example: A has 10 instances, B 5, C 7.
AVAILABLE = [3, 3, 2]
MAXIMUM = [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]]
ALLOCATION = [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]]


# ---------------------------------------------------------------- Banker's algorithm

def test_bankers_safe_sequence_textbook():
    # Need = Max - Allocation. Pass 1: P1 (1,2,2 <= 3,3,2) -> work 5,3,2; P3 -> 7,4,3;
    # P4 -> 7,4,5.  Pass 2: P0 -> 7,5,5; P2 -> 10,5,7.
    result = bankers_safety(AVAILABLE, MAXIMUM, ALLOCATION)

    assert result["safe"] is True
    assert result["sequence"] == [1, 3, 4, 0, 2]
    assert result["need"][0] == [7, 4, 3]
    assert result["steps"][-1]["work_after"] == [10, 5, 7]


def test_bankers_unsafe_state():
    # One resource type, 1 free; both processes may still need 2 more -> nobody can finish.
    result = bankers_safety([1], [[3], [3]], [[1], [1]])

    assert result["safe"] is False
    assert result["sequence"] == []


def test_bankers_request_granted_when_safe():
    # Textbook: P1 requests (1,0,2) -> new available (2,3,0), still safe.
    result = bankers_request(1, [1, 0, 2], AVAILABLE, MAXIMUM, ALLOCATION)

    assert result["granted"] is True
    assert result["available"] == [2, 3, 0]
    assert result["allocation"][1] == [3, 0, 2]
    assert result["safety"]["sequence"] == [1, 3, 4, 0, 2]


def test_bankers_request_must_wait_when_not_available():
    # After P1's grant, P4 asks for (3,3,0) but only (2,3,0) is free.
    after = bankers_request(1, [1, 0, 2], AVAILABLE, MAXIMUM, ALLOCATION)
    result = bankers_request(4, [3, 3, 0], after["available"], MAXIMUM, after["allocation"])

    assert result["granted"] is False
    assert "must wait" in result["reason"]
    assert result["safety"] is None


def test_bankers_request_denied_when_unsafe():
    # After P1's grant, P0 asks for (0,2,0): available, but the result is unsafe.
    after = bankers_request(1, [1, 0, 2], AVAILABLE, MAXIMUM, ALLOCATION)
    result = bankers_request(0, [0, 2, 0], after["available"], MAXIMUM, after["allocation"])

    assert result["granted"] is False
    assert "unsafe" in result["reason"]
    assert result["available"] == after["available"]  # state unchanged


def test_bankers_request_above_claim_is_an_error():
    with pytest.raises(ValueError, match="maximum claim"):
        bankers_request(1, [2, 0, 0], AVAILABLE, MAXIMUM, ALLOCATION)  # P1 needs only 1 A


def test_bankers_rejects_allocation_above_max():
    with pytest.raises(ValueError, match="maximum"):
        bankers_safety([1], [[1]], [[2]])


def test_bankers_rejects_bad_dimensions_and_negative_values():
    with pytest.raises(ValueError):
        bankers_safety([1, 1], [[1]], [[0]])
    with pytest.raises(ValueError):
        bankers_safety([-1], [[1]], [[0]])


# ---------------------------------------------------------------- detection

# Detection example: A has 7 instances, B 2, C 6; nothing is available.
DET_ALLOCATION = [[0, 1, 0], [2, 0, 0], [3, 0, 3], [2, 1, 1], [0, 0, 2]]
DET_REQUEST = [[0, 0, 0], [2, 0, 2], [0, 0, 0], [1, 0, 0], [0, 0, 2]]


def test_detection_no_deadlock_textbook():
    # P0 and P2 need nothing; their releases let P3, P4 and finally P1 finish.
    result = detect_deadlock([0, 0, 0], DET_ALLOCATION, DET_REQUEST)

    assert result["deadlocked"] == []
    assert result["sequence"] == [0, 2, 3, 4, 1]


def test_detection_finds_deadlock_textbook():
    # If P2 also asks for one C, only P0 can finish (freeing 0,1,0): P1-P4 are deadlocked.
    request = [row[:] for row in DET_REQUEST]
    request[2] = [0, 0, 1]
    result = detect_deadlock([0, 0, 0], DET_ALLOCATION, request)

    assert result["deadlocked"] == [1, 2, 3, 4]


def test_process_holding_nothing_is_never_deadlocked():
    result = detect_deadlock([0], [[0], [1]], [[1], [0]])

    assert result["deadlocked"] == []


def test_explain_simple_cycle():
    lines = explain_deadlock([0, 1], [[1, 0], [0, 1]], [[0, 1], [1, 0]], ["P1", "P2"], ["A", "B"])

    assert lines == ["P1 holds A x1 and waits for B x1 (held by P2)",
                     "P2 holds B x1 and waits for A x1 (held by P1)"]


def test_recovery_terminates_victim_holding_most():
    # Deadlocked P1..P4 hold 2, 6, 4, 2 instances -> P2 is the victim. Its release
    # (3,0,3) is enough for everyone else, so one victim suffices.
    request = [row[:] for row in DET_REQUEST]
    request[2] = [0, 0, 1]
    result = recover_by_termination([0, 0, 0], DET_ALLOCATION, request)

    assert result["victims"] == [2]
    assert result["available"] == [3, 0, 3]
    assert result["allocation"][2] == [0, 0, 0]
    assert detect_deadlock(result["available"], result["allocation"], result["request"])["deadlocked"] == []


def test_recovery_without_deadlock_does_nothing():
    result = recover_by_termination([0, 0, 0], DET_ALLOCATION, DET_REQUEST)

    assert result["victims"] == []


# ---------------------------------------------------------------- resource manager

def make_manager():
    rm = ResourceManager({"R1": 1, "R2": 2})
    for pid in ("P1", "P2", "P3"):
        rm.add_process(pid)
    return rm


def test_request_granted_and_queued():
    rm = make_manager()

    assert rm.request("P1", "R1", 1) is True
    assert rm.request("P2", "R1", 1) is False  # only one R1 exists
    assert rm.available["R1"] == 0
    assert rm.waiting_for("P2") == {"pid": "P2", "resource": "R1", "count": 1}
    rm.check_invariants()


def test_release_lets_waiting_request_through():
    rm = make_manager()
    rm.request("P1", "R1", 1)
    rm.request("P2", "R1", 1)

    rm.release("P1", "R1", 1)
    granted = rm.grant_waiting()

    assert granted == [{"pid": "P2", "resource": "R1", "count": 1}]
    assert rm.holding("P2", "R1") == 1 and rm.waiting == []
    rm.check_invariants()


def test_waiting_requests_granted_fifo_skipping_ones_that_do_not_fit():
    rm = make_manager()
    rm.request("P1", "R2", 2)
    rm.request("P2", "R2", 2)  # waits (first in line)
    rm.request("P3", "R2", 1)  # waits
    rm.release("P1", "R2", 1)  # only 1 free: P2's request does not fit, P3's does

    assert [g["pid"] for g in rm.grant_waiting()] == ["P3"]


def test_cannot_release_what_is_not_held():
    rm = make_manager()
    with pytest.raises(ValueError, match="cannot release"):
        rm.release("P1", "R1", 1)


def test_cannot_hold_more_than_exist():
    rm = make_manager()
    with pytest.raises(ValueError, match="more"):
        rm.request("P1", "R2", 3)


def test_unknown_resource_and_bad_count():
    rm = make_manager()
    with pytest.raises(ValueError, match="Unknown resource"):
        rm.request("P1", "R9", 1)
    with pytest.raises(ValueError, match="positive"):
        rm.request("P1", "R1", 0)


def test_cannot_request_while_already_waiting():
    rm = make_manager()
    rm.request("P1", "R1", 1)
    rm.request("P2", "R1", 1)
    with pytest.raises(ValueError, match="already waiting"):
        rm.request("P2", "R2", 1)


def test_manager_detects_cycle_and_picks_victim():
    rm = ResourceManager({"A": 1, "B": 1})
    for pid in ("P1", "P2"):
        rm.add_process(pid)
    rm.request("P1", "A", 1)
    rm.request("P2", "B", 1)
    rm.request("P1", "B", 1)
    rm.request("P2", "A", 1)

    result = rm.detect()
    assert result["deadlocked"] == ["P1", "P2"]
    assert "P1 holds A x1 and waits for B x1 (held by P2)" in result["explanation"]
    assert rm.pick_victim(result["deadlocked"]) == "P1"  # tie on holdings -> first

    assert rm.release_all("P1") == {"A": 1}
    assert rm.waiting_for("P1") is None
    assert [g["pid"] for g in rm.grant_waiting()] == ["P2"]
    assert rm.detect()["deadlocked"] == []
    rm.check_invariants()


def test_parse_resources():
    assert parse_resources("printer=1, scanner = 2") == {"printer": 1, "scanner": 2}
    with pytest.raises(ValueError):
        parse_resources("printer")
    with pytest.raises(ValueError):
        ResourceManager(parse_resources("printer=0"))

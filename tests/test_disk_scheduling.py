"""Tests for disk scheduling.

Main example (Silberschatz/Galvin): queue 98 183 37 122 14 124 65 67,
head at 53, cylinders 0-199.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.disk_scheduling import compare_policies, parse_requests, schedule

QUEUE = [98, 183, 37, 122, 14, 124, 65, 67]


def test_fcfs():
    # 45+85+146+85+108+110+59+2 = 640
    result = schedule("FCFS", QUEUE, 53)

    assert result["order"] == QUEUE
    assert result["total_movement"] == 640


def test_sstf():
    # 53->65(12)->67(2)->37(30)->14(23)->98(84)->122(24)->124(2)->183(59) = 236
    result = schedule("SSTF", QUEUE, 53)

    assert result["order"] == [65, 67, 37, 14, 98, 122, 124, 183]
    assert result["total_movement"] == 236


def test_scan_moving_down():
    # 53->37->14->0 (edge) then up to 183: 53 + 183 = 236
    result = schedule("SCAN", QUEUE, 53, direction="down")

    assert result["path"] == [53, 37, 14, 0, 65, 67, 98, 122, 124, 183]
    assert result["total_movement"] == 236


def test_scan_moving_up():
    # 53->183 (130), ->199 edge (16), back to 37 (162), ->14 (23) = 331
    result = schedule("SCAN", QUEUE, 53, direction="up")

    assert result["path"] == [53, 65, 67, 98, 122, 124, 183, 199, 37, 14]
    assert result["total_movement"] == 331


def test_cscan_moving_up_counts_the_return_jump():
    # 53->199 (146), jump 199->0 (199), 0->14->37 (37) = 382
    result = schedule("C-SCAN", QUEUE, 53, direction="up")

    assert result["path"] == [53, 65, 67, 98, 122, 124, 183, 199, 0, 14, 37]
    assert result["order"] == [65, 67, 98, 122, 124, 183, 14, 37]
    assert result["total_movement"] == 382


def test_cscan_moving_down():
    # 53->0 (53), jump to 199 (199), down to 65 (134) = 386
    result = schedule("C-SCAN", QUEUE, 53, direction="down")

    assert result["order"] == [37, 14, 183, 124, 122, 98, 67, 65]
    assert result["total_movement"] == 386


def test_look_moving_up():
    # 53->183 (130), reverse at the last request, ->37 (146), ->14 (23) = 299
    result = schedule("LOOK", QUEUE, 53, direction="up")

    assert result["path"] == [53, 65, 67, 98, 122, 124, 183, 37, 14]
    assert result["total_movement"] == 299


def test_look_moving_down():
    # 53->14 (39), reverse, ->183 (169) = 208
    assert schedule("LOOK", QUEUE, 53, direction="down")["total_movement"] == 208


def test_clook_moving_up():
    # 53->183 (130), jump to 14 (169), ->37 (23) = 322
    result = schedule("C-LOOK", QUEUE, 53, direction="up")

    assert result["order"] == [65, 67, 98, 122, 124, 183, 14, 37]
    assert result["total_movement"] == 322


def test_clook_moving_down():
    # 53->14 (39), jump to 183 (169), ->65 (118) = 326
    assert schedule("C-LOOK", QUEUE, 53, direction="down")["total_movement"] == 326


# ---------------------------------------------------------------- edge cases

def test_scan_starting_at_the_edge_does_not_move_to_it_again():
    # Head already at 199 moving up: nothing ahead, reverse immediately.
    result = schedule("SCAN", [10, 50], 199, direction="up")

    assert result["path"] == [199, 50, 10]
    assert result["total_movement"] == 189


def test_cscan_starting_at_the_edge():
    # 199 -> jump to 0 (199) -> 10 -> 50 (50) = 249
    result = schedule("C-SCAN", [10, 50], 199, direction="up")

    assert result["path"] == [199, 0, 10, 50]
    assert result["total_movement"] == 249


def test_cscan_request_on_the_opposite_edge():
    # 50->60 (10), ->199 (139), jump ->0 (199) which is also the request: 348
    result = schedule("C-SCAN", [60, 0], 50, direction="up")

    assert result["path"] == [50, 60, 199, 0]
    assert result["total_movement"] == 348


def test_scan_requests_only_behind_the_head():
    # Moving up with nothing above: SCAN goes to the edge first, LOOK turns at once.
    assert schedule("SCAN", [20, 10], 50, direction="up")["total_movement"] == 149 + 179 + 10
    assert schedule("LOOK", [20, 10], 50, direction="up")["total_movement"] == 40


def test_scan_does_not_go_to_edge_when_nothing_is_left():
    # All requests are ahead: the head stops at the last one.
    result = schedule("SCAN", [60, 70], 50, direction="up")

    assert result["path"] == [50, 60, 70]


def test_repeated_requests_and_request_at_head():
    # Request at the head costs 0; the duplicate 20 costs 0 the second time.
    for policy in ("FCFS", "SSTF", "SCAN", "C-SCAN", "LOOK", "C-LOOK"):
        result = schedule(policy, [10, 20, 20, 10], 10, direction="up")
        assert sorted(result["order"]) == [10, 10, 20, 20]
        assert result["total_movement"] == (20 if policy == "FCFS" else 10)


def test_sstf_tie_goes_to_lower_cylinder():
    assert schedule("SSTF", [60, 40], 50)["order"] == [40, 60]


def test_steps_add_up_to_total():
    result = schedule("C-LOOK", QUEUE, 53)

    assert sum(s["distance"] for s in result["steps"]) == result["total_movement"]


def test_compare_policies():
    rows = {r["policy"]: r["total_movement"] for r in compare_policies(QUEUE, 53, 200, "up")}

    assert rows == {"FCFS": 640, "SSTF": 236, "SCAN": 331, "C-SCAN": 382, "LOOK": 299, "C-LOOK": 322}


# ---------------------------------------------------------------- invalid input

@pytest.mark.parametrize("requests, head, size, direction", [
    ([], 50, 200, "up"),
    ([200], 50, 200, "up"),
    ([-1], 50, 200, "up"),
    ([10], 200, 200, "up"),
    ([10], 50, 0, "up"),
    ([10], 50, 200, "left"),
])
def test_invalid_input(requests, head, size, direction):
    with pytest.raises(ValueError):
        schedule("FCFS", requests, head, size, direction)


def test_unknown_policy():
    with pytest.raises(ValueError, match="Unknown"):
        schedule("ELEVATOR", [1], 0)


def test_parse_requests():
    assert parse_requests("98, 183 37") == [98, 183, 37]
    with pytest.raises(ValueError):
        parse_requests("1 x")

"""Tests for First Fit, Best Fit and Worst Fit.

Main example (Silberschatz): blocks 100, 500, 200, 300, 600 and
processes of 212, 417, 112, 426. Block numbers below are 0-based.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.memory_allocation import allocate, compare_strategies

BLOCKS = [100, 500, 200, 300, 600]
REQUESTS = [{"pid": "P1", "size": 212}, {"pid": "P2", "size": 417},
            {"pid": "P3", "size": 112}, {"pid": "P4", "size": 426}]


def placed(result):
    return [a["block"] for a in result["allocations"]]


# ---------------------------------------------------------------- variable partitioning

def test_first_fit_variable():
    # 212 -> 500 (288 left), 417 -> 600 (183 left), 112 -> the 288 hole (176 left),
    # 426 fits nowhere.
    result = allocate(BLOCKS, REQUESTS, "First Fit")

    assert placed(result) == [1, 4, 1, None]
    assert [b["free"] for b in result["blocks"]] == [100, 176, 200, 300, 183]
    assert result["unallocated"] == ["P4"]
    assert result["blocks"][1]["segments"] == [("P1", 212), ("P3", 112)]


def test_best_fit_variable():
    # 212 -> 300, 417 -> 500, 112 -> 200, 426 -> 600: everything fits.
    result = allocate(BLOCKS, REQUESTS, "Best Fit")

    assert placed(result) == [3, 1, 2, 4]
    assert result["unallocated"] == []
    assert result["external_fragmentation"] == 0


def test_worst_fit_variable():
    # 212 -> 600 (388 left), 417 -> 500 (83 left), 112 -> the 388 hole, 426 fails.
    result = allocate(BLOCKS, REQUESTS, "Worst Fit")

    assert placed(result) == [4, 1, 4, None]
    assert result["blocks"][4]["free"] == 600 - 212 - 112


def test_external_fragmentation_when_memory_is_split():
    # First Fit leaves 100+176+200+300+183 = 959 free, yet 426 does not fit in one hole.
    result = allocate(BLOCKS, REQUESTS, "First Fit")

    assert result["total_free"] == 959
    assert result["largest_free"] == 300
    assert result["external_fragmentation"] == 959
    assert result["internal_fragmentation"] is None  # not measured in the variable model


def test_no_external_fragmentation_if_memory_is_simply_too_small():
    # 50 free in total, request needs 80: that is a shortage, not fragmentation.
    result = allocate([30, 20], [{"pid": "A", "size": 80}], "First Fit")

    assert result["unallocated"] == ["A"]
    assert result["external_fragmentation"] == 0


# ---------------------------------------------------------------- fixed partitioning

def test_first_fit_fixed():
    # One process per block. 212 -> 500, 417 -> 600, 112 -> 200, 426 -> none (300 too small).
    # Internal fragmentation: (500-212) + (600-417) + (200-112) = 288 + 183 + 88 = 559
    result = allocate(BLOCKS, REQUESTS, "First Fit", mode="fixed")

    assert placed(result) == [1, 4, 2, None]
    assert result["internal_fragmentation"] == 559


def test_best_fit_fixed():
    # 212 -> 300 (88), 417 -> 500 (83), 112 -> 200 (88), 426 -> 600 (174): 433
    result = allocate(BLOCKS, REQUESTS, "Best Fit", mode="fixed")

    assert placed(result) == [3, 1, 2, 4]
    assert result["internal_fragmentation"] == 433


def test_worst_fit_fixed():
    # 212 -> 600 (388), 417 -> 500 (83), 112 -> 300 (188), 426 fails: 659
    result = allocate(BLOCKS, REQUESTS, "Worst Fit", mode="fixed")

    assert placed(result) == [4, 1, 3, None]
    assert result["internal_fragmentation"] == 659
    # Free partitions left: 100 and 200 = 300 < 426, so no external fragmentation counted.
    assert result["total_free"] == 300
    assert result["external_fragmentation"] == 0


def test_fixed_partition_holds_only_one_process():
    result = allocate([100], [{"pid": "A", "size": 10}, {"pid": "B", "size": 10}],
                      "First Fit", mode="fixed")

    assert result["unallocated"] == ["B"]


def test_ties_go_to_lowest_block_number():
    result = allocate([50, 50], [{"pid": "A", "size": 50}], "Best Fit")

    assert placed(result) == [0]


def test_exact_fit_leaves_zero_free():
    result = allocate([100], [{"pid": "A", "size": 100}], "First Fit")

    assert result["blocks"][0]["free"] == 0


def test_compare_strategies():
    rows = {r["strategy"]: r for r in compare_strategies(BLOCKS, REQUESTS)}

    assert rows["Best Fit"]["allocated"] == 4
    assert rows["First Fit"]["unallocated"] == "P4"
    assert rows["Worst Fit"]["unallocated"] == "P4"


# ---------------------------------------------------------------- invalid input

@pytest.mark.parametrize("blocks", [[], [0, 100], [-5], [1.5]])
def test_invalid_blocks(blocks):
    with pytest.raises(ValueError, match="block"):
        allocate(blocks, REQUESTS)


@pytest.mark.parametrize("size", [0, -10, 2.5])
def test_invalid_request_size(size):
    with pytest.raises(ValueError, match="size"):
        allocate(BLOCKS, [{"pid": "A", "size": size}])


def test_duplicate_process_name():
    with pytest.raises(ValueError, match="Duplicate"):
        allocate(BLOCKS, [{"pid": "A", "size": 1}, {"pid": "A", "size": 2}])


def test_unknown_strategy_and_mode():
    with pytest.raises(ValueError):
        allocate(BLOCKS, REQUESTS, "Next Fit")
    with pytest.raises(ValueError):
        allocate(BLOCKS, REQUESTS, "First Fit", mode="paged")

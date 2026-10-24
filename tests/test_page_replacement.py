"""Tests for FIFO page replacement.

Expected values were worked out by hand; the working is in each comment.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algorithms.page_replacement import (compare_page_replacement, fifo_page_replacement,
                                         lru_page_replacement, optimal_page_replacement,
                                         page_replacement, parse_reference_string)


def test_hit_when_page_already_in_memory():
    # 1 fault [1,-,-]; 2 fault [1,2,-]; 1 is already loaded -> hit, frames unchanged
    result = fifo_page_replacement([1, 2, 1], 3)

    assert [s["hit"] for s in result["steps"]] == [False, False, True]
    assert result["steps"][2]["frames"] == [1, 2, None]
    assert result["steps"][2]["replaced"] is None
    assert (result["hits"], result["faults"]) == (1, 2)


def test_hit_does_not_change_which_page_is_oldest():
    # Frames=2.  1 -> [1,-]; 2 -> [1,2]; 1 is a hit.  If a hit refreshed page 1
    # (as LRU would), 3 would evict 2.  FIFO evicts 1, the oldest load: [3,2].
    result = fifo_page_replacement([1, 2, 1, 3], 2)

    assert result["steps"][3]["frames"] == [3, 2]
    assert result["steps"][3]["replaced"] == 1


def test_replacement_when_frames_are_full():
    # Frames=3.  1,2,3 fill.  4 evicts 1 -> [4,2,3].  5 evicts 2 -> [4,5,3].
    result = fifo_page_replacement([1, 2, 3, 4, 5], 3)

    assert result["steps"][2]["frames"] == [1, 2, 3]
    assert result["steps"][3]["frames"] == [4, 2, 3]
    assert result["steps"][3]["replaced"] == 1
    assert result["steps"][4]["frames"] == [4, 5, 3]
    assert result["steps"][4]["replaced"] == 2
    assert (result["hits"], result["faults"]) == (0, 5)


def test_textbook_sequence_with_three_frames():
    # Classic example: 7 0 1 2 0 3 0 4 2 3 0 3 2 1 2 0 1 7 0 1 with 3 frames.
    # Frame contents after each reference, traced by hand (frame slot order is
    # fixed; a replaced page takes the slot of the page it evicts).
    # Hits are references 5 (0), 12 (3), 13 (2), 16 (0) and 17 (1).
    reference = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
    result = fifo_page_replacement(reference, 3)

    expected_frames = [
        [7, None, None], [7, 0, None], [7, 0, 1], [2, 0, 1], [2, 0, 1],
        [2, 3, 1], [2, 3, 0], [4, 3, 0], [4, 2, 0], [4, 2, 3],
        [0, 2, 3], [0, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2],
        [0, 1, 2], [0, 1, 2], [7, 1, 2], [7, 0, 2], [7, 0, 1],
    ]
    assert [s["frames"] for s in result["steps"]] == expected_frames
    assert [s["step"] for s in result["steps"] if s["hit"]] == [5, 12, 13, 16, 17]
    assert result["faults"] == 15
    assert result["hits"] == 5
    assert result["fault_ratio"] == pytest.approx(0.75)


def test_loaded_into_reports_the_frame_that_received_the_page():
    # Frames=2: 1 -> frame 0, 2 -> frame 1, 1 is a hit (None), 3 evicts 1 -> frame 0,
    # 4 evicts 2 -> frame 1.
    result = fifo_page_replacement([1, 2, 1, 3, 4], 2)

    assert [s["loaded_into"] for s in result["steps"]] == [0, 1, None, 0, 1]


def test_beladys_anomaly_sequence():
    # 1 2 3 4 1 2 5 1 2 3 4 5 is the standard FIFO example:
    # 9 faults with 3 frames, 10 faults with 4 frames (more frames, more faults).
    reference = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]

    assert fifo_page_replacement(reference, 3)["faults"] == 9
    assert fifo_page_replacement(reference, 4)["faults"] == 10


def test_repeated_same_page_faults_only_once():
    result = fifo_page_replacement([5, 5, 5, 5], 2)

    assert [s["hit"] for s in result["steps"]] == [False, True, True, True]
    assert (result["hits"], result["faults"]) == (3, 1)
    assert result["hit_ratio"] == pytest.approx(0.75)
    assert result["fault_ratio"] == pytest.approx(0.25)


def test_single_frame_only_immediate_repeats_hit():
    result = fifo_page_replacement([1, 2, 2, 1], 1)

    assert [s["hit"] for s in result["steps"]] == [False, False, True, False]
    assert result["steps"][3]["replaced"] == 2


def test_more_frames_than_distinct_pages_never_replaces():
    result = fifo_page_replacement([1, 2, 1, 2, 3], 10)

    assert result["faults"] == 3
    assert all(s["replaced"] is None for s in result["steps"])


def test_single_reference():
    result = fifo_page_replacement([4], 3)

    assert result["steps"][0]["frames"] == [4, None, None]
    assert (result["hits"], result["faults"]) == (0, 1)
    assert result["fault_ratio"] == 1.0


def test_snapshots_are_independent_copies():
    # Later steps must not change the frames recorded in earlier steps.
    result = fifo_page_replacement([1, 2, 3], 3)

    assert result["steps"][0]["frames"] == [1, None, None]


def test_page_zero_is_a_valid_page():
    # Guards against code that treats 0 as "empty frame".
    result = fifo_page_replacement([0, 0], 2)

    assert [s["hit"] for s in result["steps"]] == [False, True]


# --------------------------------------------------- invalid input

@pytest.mark.parametrize("frames", [0, -1, 2.5, "3", True])
def test_invalid_frame_count(frames):
    with pytest.raises(ValueError, match="frames"):
        fifo_page_replacement([1, 2, 3], frames)


def test_empty_reference_sequence():
    with pytest.raises(ValueError, match="empty"):
        fifo_page_replacement([], 3)


def test_negative_page_number():
    with pytest.raises(ValueError, match="non-negative"):
        fifo_page_replacement([1, -2, 3], 3)


# --------------------------------------------------- input parsing

def test_parse_accepts_spaces_and_commas():
    assert parse_reference_string("7 0 1, 2,0") == [7, 0, 1, 2, 0]


@pytest.mark.parametrize("text", ["", "   ", "1 a 3", "1.5 2"])
def test_parse_rejects_bad_text(text):
    with pytest.raises(ValueError):
        parse_reference_string(text)


# --------------------------------------------------- LRU and Optimal

TEXTBOOK = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]


def test_lru_textbook_sequence():
    # Traced by hand: 12 faults; hits at references 5, 7, 12, 13, 15, 17, 19, 20.
    # e.g. ref 4 (page 2) evicts 7 (least recently used), ref 6 (page 3) evicts 1.
    result = lru_page_replacement(TEXTBOOK, 3)

    assert result["faults"] == 12
    assert [s["step"] for s in result["steps"] if s["hit"]] == [5, 7, 12, 13, 15, 17, 19, 20]
    assert result["steps"][3]["frames"] == [2, 0, 1] and result["steps"][3]["replaced"] == 7
    assert result["steps"][5]["frames"] == [2, 0, 3] and result["steps"][5]["replaced"] == 1
    assert result["steps"][-1]["frames"] == [1, 0, 7]


def test_lru_hit_refreshes_the_page():
    # Same input as the FIFO test above: 1, 2, 1(hit), 3. LRU evicts 2 because 1 was just used.
    result = lru_page_replacement([1, 2, 1, 3], 2)

    assert result["steps"][3]["frames"] == [1, 3]
    assert result["steps"][3]["replaced"] == 2


def test_optimal_textbook_sequence():
    # 9 faults. Ref 4 (page 2): next uses 7@18, 0@5, 1@14 -> evict 7.
    # Ref 6 (page 3): 2@9, 0@7, 1@14 -> evict 1.
    result = optimal_page_replacement(TEXTBOOK, 3)

    assert result["faults"] == 9
    assert result["steps"][3]["replaced"] == 7
    assert result["steps"][5]["replaced"] == 1
    assert result["steps"][-1]["frames"] == [7, 0, 1]


def test_optimal_tie_evicts_page_loaded_first():
    # 1 2 3 4 1 2 5 1 2 3 4 5 with 3 frames. At ref 10 (page 3) the frames are [1,2,5]:
    # 1 and 2 are never used again -> tie -> evict 1 (loaded first). Frames [3,2,5].
    result = optimal_page_replacement([1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5], 3)

    assert result["steps"][9]["frames"] == [3, 2, 5]
    assert result["steps"][10]["frames"] == [3, 4, 5]
    assert result["faults"] == 7


def test_lru_and_optimal_fault_counts_on_belady_sequence():
    reference = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]

    assert lru_page_replacement(reference, 3)["faults"] == 10
    assert lru_page_replacement(reference, 4)["faults"] == 8
    assert optimal_page_replacement(reference, 3)["faults"] == 7
    assert optimal_page_replacement(reference, 4)["faults"] == 6


def test_compare_page_replacement_same_input():
    rows = {r["algorithm"]: r["faults"] for r in compare_page_replacement(TEXTBOOK, 3)}

    assert rows == {"FIFO": 15, "LRU": 12, "Optimal": 9}


@pytest.mark.parametrize("algorithm", ["LRU", "Optimal"])
def test_new_algorithms_validate_input(algorithm):
    with pytest.raises(ValueError, match="frames"):
        page_replacement([1, 2], 0, algorithm)
    with pytest.raises(ValueError, match="empty"):
        page_replacement([], 3, algorithm)


def test_unknown_page_algorithm():
    with pytest.raises(ValueError, match="Unknown"):
        page_replacement([1], 1, "Clock")

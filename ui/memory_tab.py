"""Memory Management page: page replacement, contiguous allocation, and how they differ."""

import pandas as pd
import streamlit as st

from algorithms.memory_allocation import STRATEGIES, allocate, compare_strategies
from algorithms.page_replacement import (ALGORITHMS, compare_page_replacement, page_replacement,
                                         parse_reference_string)
from ui import charts
from ui.common import (BAD_STYLE, GOOD_STYLE, NEW_STYLE, is_blank, log_activity, parse_numbers,
                       whole_number)

SAMPLE_REFERENCE = "7 0 1 2 0 3 0 4 2 3 0 3 2 1 2 0 1 7 0 1"
SAMPLE_BLOCKS = "100, 500, 200, 300, 600"
SAMPLE_REQUESTS = [{"pid": "P1", "size": 212}, {"pid": "P2", "size": 417},
                   {"pid": "P3", "size": 112}, {"pid": "P4", "size": 426}]


# ------------------------------------------------------------ page replacement

def step_table(result):
    """One row per page reference with hit/fault colours and the frame that changed."""
    rows = []
    for s in result["steps"]:
        row = {"Step": s["step"], "Page": s["page"]}
        for i, page in enumerate(s["frames"]):
            row[f"Frame {i + 1}"] = "-" if page is None else str(page)
        row["Result"] = "HIT" if s["hit"] else "FAULT"
        row["Evicted"] = "" if s["replaced"] is None else str(s["replaced"])
        rows.append(row)
    table = pd.DataFrame(rows)

    def colour_row(row):
        styles = [""] * len(row)
        styles[row.index.get_loc("Result")] = GOOD_STYLE if row["Result"] == "HIT" else BAD_STYLE
        slot = result["steps"][row.name]["loaded_into"]
        if slot is not None:  # highlight the frame that just received the new page
            styles[row.index.get_loc(f"Frame {slot + 1}")] = NEW_STYLE
        return styles

    return table.style.apply(colour_row, axis=1)


def page_replacement_section():
    st.write(
        "Enter a page reference sequence (numbers separated by spaces or commas) and the number "
        "of frames. On a page fault with all frames full, the algorithm chooses a victim: "
        "**FIFO** evicts the page loaded longest ago, **LRU** the page used longest ago, and "
        "**Optimal** the page that will not be needed for the longest time (it needs to know "
        "the future, so it is only a benchmark)."
    )
    col_seq, col_frames = st.columns([3, 1])
    text = col_seq.text_input("Page reference sequence", value=SAMPLE_REFERENCE)
    num_frames = col_frames.number_input("Number of frames", value=3, step=1)
    algorithm = st.radio("Algorithm", ALGORITHMS, horizontal=True)

    col_run, col_compare = st.columns(2)
    if col_run.button("Run page replacement", type="primary"):
        try:
            reference = parse_reference_string(text)
            result = page_replacement(reference, int(num_frames), algorithm)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_paging = {"frames": int(num_frames), "reference": reference,
                                            "result": result}
            log_activity("MEMORY", "PAGE_REPLACEMENT",
                         f"{algorithm}: {len(reference)} references, {int(num_frames)} frames "
                         f"({result['faults']} faults, {result['hits']} hits)")
    if col_compare.button("Compare FIFO, LRU and Optimal"):
        try:
            rows = compare_page_replacement(parse_reference_string(text), int(num_frames))
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_paging_compare = {"frames": int(num_frames), "rows": rows}
            log_activity("MEMORY", "COMPARE", "page faults: " +
                         ", ".join(f"{r['algorithm']} {r['faults']}" for r in rows))

    last = st.session_state.last_paging
    if last is None:
        st.info("Press 'Run page replacement' to see the frame contents after every reference.")
    else:
        result = last["result"]
        st.subheader(f"{result['algorithm']}: {len(last['reference'])} references, {last['frames']} frames")
        st.caption("Reference sequence: " + " ".join(str(p) for p in last["reference"]))
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Page hits", result["hits"])
        col2.metric("Page faults", result["faults"])
        col3.metric("Page-fault ratio", f"{result['fault_ratio']:.2f}")
        col4.metric("Page-hit ratio", f"{result['hit_ratio']:.2f}")
        st.markdown("**Frame contents after each reference**")
        st.caption("Green = HIT, red = FAULT. The yellow cell is the frame that received the new "
                   "page. '-' means the frame is still empty.")
        st.dataframe(step_table(result), hide_index=True)

    comparison = st.session_state.last_paging_compare
    if comparison is not None:
        st.subheader(f"Comparison with {comparison['frames']} frames")
        frame = pd.DataFrame(comparison["rows"]).rename(columns={
            "algorithm": "Algorithm", "hits": "Hits", "faults": "Faults", "fault_ratio": "Fault ratio"})
        st.dataframe(frame.style.format({"Fault ratio": "{:.2f}"}), hide_index=True)
        st.bar_chart(frame, x="Algorithm", y="Faults")


# ------------------------------------------------------------ contiguous allocation

def read_requests(table):
    requests = []
    for _, row in table.iterrows():
        if is_blank(row["pid"]) and is_blank(row["size"]):
            continue
        if is_blank(row["pid"]) or is_blank(row["size"]):
            raise ValueError("Every request needs a process name and a size.")
        pid = str(row["pid"]).strip()
        requests.append({"pid": pid, "size": whole_number(row["size"], pid, "size")})
    return requests


def allocation_section():
    st.write(
        "Memory is a list of blocks (holes). Each process needs **one contiguous piece**. "
        "**First Fit** takes the first block that is big enough, **Best Fit** the smallest that "
        "fits, **Worst Fit** the largest."
    )
    st.write(
        "*Variable partitions*: a process takes only what it needs and the rest of the hole stays "
        "free, so the waste is **external fragmentation** (free memory split into holes too small "
        "to use). *Fixed partitions*: a block holds one process and its unused space is wasted "
        "inside it, which is **internal fragmentation**."
    )
    blocks_text = st.text_input("Memory block sizes", value=SAMPLE_BLOCKS)
    st.button("Reset requests to sample data",
              on_click=lambda: st.session_state.pop("alloc_editor", None))
    table = st.data_editor(
        pd.DataFrame(SAMPLE_REQUESTS), key="alloc_editor", num_rows="dynamic", hide_index=True,
        column_config={"pid": st.column_config.TextColumn("Process"),
                       "size": st.column_config.NumberColumn("Size", step=1, format="%d")},
    )
    col_strategy, col_mode = st.columns(2)
    strategy = col_strategy.radio("Strategy", STRATEGIES, horizontal=True)
    mode_label = col_mode.radio("Partition model", ["Variable partitions", "Fixed partitions"],
                                horizontal=True)
    mode = "variable" if mode_label.startswith("Variable") else "fixed"

    col_run, col_compare = st.columns(2)
    if col_run.button("Allocate memory", type="primary"):
        try:
            result = allocate(parse_numbers(blocks_text, "Block sizes"), read_requests(table), strategy, mode)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_alloc = result
            log_activity("MEMORY", "ALLOCATE", f"{strategy} ({mode} partitions): "
                                               f"{len(result['unallocated'])} process(es) not allocated")
    if col_compare.button("Compare the three strategies"):
        try:
            rows = compare_strategies(parse_numbers(blocks_text, "Block sizes"), read_requests(table), mode)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_alloc_compare = {"mode": mode, "rows": rows}

    result = st.session_state.last_alloc
    if result is None:
        st.info("Press 'Allocate memory' to place the processes.")
    else:
        st.subheader(f"{result['strategy']} with {result['mode']} partitions")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Not allocated", ", ".join(result["unallocated"]) or "none")
        col2.metric("Free memory left", result["total_free"])
        col3.metric("Internal fragmentation",
                    "n/a" if result["internal_fragmentation"] is None else result["internal_fragmentation"])
        col4.metric("External fragmentation", result["external_fragmentation"])
        st.pyplot(charts.memory_layout(result["blocks"]))
        left, right = st.columns(2)
        left.markdown("**Allocations**")
        left.dataframe(pd.DataFrame([
            {"Process": a["pid"], "Size": a["size"],
             "Block": "not allocated" if a["block"] is None else f"Block {a['block'] + 1}"}
            for a in result["allocations"]
        ]), hide_index=True)
        right.markdown("**Blocks after allocation**")
        right.dataframe(pd.DataFrame([
            {"Block": b["block"] + 1, "Size": b["size"],
             "Processes": ", ".join(pid for pid, _ in b["segments"]) or "-", "Remaining": b["free"]}
            for b in result["blocks"]
        ]), hide_index=True)
        st.caption("External fragmentation is reported as the total free memory when a waiting "
                   "process would fit in that total but not in any single block; otherwise 0.")

    comparison = st.session_state.last_alloc_compare
    if comparison is not None:
        st.subheader(f"Strategy comparison ({comparison['mode']} partitions)")
        st.dataframe(pd.DataFrame(comparison["rows"]).rename(columns={
            "strategy": "Strategy", "allocated": "Allocated", "unallocated": "Not allocated",
            "total_free": "Free left", "largest_free": "Largest free piece",
            "internal_fragmentation": "Internal frag.", "external_fragmentation": "External frag.",
        }), hide_index=True)


def differences_section():
    st.markdown(
        """
| | Contiguous allocation | Paging |
|---|---|---|
| Unit of allocation | One variable-size block per process | Fixed-size pages placed in fixed-size frames |
| Must a process be in one piece? | Yes | No: pages can be in any free frames |
| Fragmentation | External (variable partitions) or internal (fixed partitions) | No external fragmentation; at most part of the last page is unused |
| Address translation | Base + offset | Page table maps each virtual page to a frame |
| When memory is full | The process must wait (or memory is compacted) | A page is evicted by a replacement policy (FIFO, LRU, ...) |
"""
    )
    st.write(
        "The **Integrated Simulation** uses paging: every process has a page table, physical "
        "frames are shared, and a MEM instruction for a page that is not resident causes a page "
        "fault that blocks the process until the page-in finishes. It supports FIFO and LRU "
        "replacement; Optimal is not offered there because the simulation does not know every "
        "process's future memory accesses."
    )


def render():
    st.header("Memory Management")
    tab_paging, tab_alloc, tab_diff = st.tabs(
        ["Page replacement", "Contiguous allocation", "Paging vs. contiguous allocation"])
    with tab_paging:
        page_replacement_section()
    with tab_alloc:
        allocation_section()
    with tab_diff:
        differences_section()

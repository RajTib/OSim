"""Small helpers shared by the UI pages.

Streamlit re-runs the whole script on every click, so anything that must
survive a re-run (latest results, the activity log, the running simulation)
is kept in st.session_state.
"""

import time

import pandas as pd
import streamlit as st

# Cell styles for hit/fault tables (dark text so they are readable in any theme)
GOOD_STYLE = "background-color: #c8e6c9; color: #000000; font-weight: bold"
BAD_STYLE = "background-color: #ffcdd2; color: #000000; font-weight: bold"
NEW_STYLE = "background-color: #fff59d; color: #000000; font-weight: bold"


def init_state():
    """Create the session-state entries on the first run only."""
    st.session_state.setdefault("activity", [])  # standalone-module log
    for key in ("last_cpu", "last_cpu_compare", "last_paging", "last_paging_compare",
                "last_alloc", "last_alloc_compare", "last_disk", "last_disk_compare",
                "last_bankers"):
        st.session_state.setdefault(key, None)


def log_activity(section, event, details):
    """Record a standalone-module action for the Event Log page."""
    st.session_state.activity.append({
        "time": time.strftime("%H:%M:%S"), "section": section, "event": event, "details": details,
    })


def is_blank(value):
    return value is None or pd.isna(value) or str(value).strip() == ""


def whole_number(value, owner, label):
    """The table editor may hand back floats (e.g. 3.0); accept them only if whole."""
    if float(value) != int(float(value)):
        raise ValueError(f"{owner}: {label} must be a whole number.")
    return int(value)


def parse_numbers(text, what):
    """'1, 2 3' -> [1, 2, 3]"""
    tokens = text.replace(",", " ").split()
    try:
        return [int(t) for t in tokens]
    except ValueError:
        raise ValueError(f"{what} must be whole numbers separated by spaces or commas.") from None


def fmt(value, digits=2):
    return "-" if value is None else f"{value:.{digits}f}"

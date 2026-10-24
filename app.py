"""OSim - Streamlit interface.

Run with:  streamlit run app.py

This file only sets up the page and the navigation. Each section lives in
ui/<section>.py, and all the actual OS logic lives in algorithms/, simulation/
and filesystem/ (none of which import Streamlit).

Data flow:
    user input -> algorithm function or Simulation method -> result / updated state
               -> st.session_state -> tables and charts
Streamlit re-runs this whole script on every click, so results, the activity
log and the integrated Simulation object are kept in st.session_state.
"""

import time

import streamlit as st

from ui import cpu_tab, dashboard, deadlock_tab, memory_tab, simulation_tab, storage_tab
from ui.common import init_state

PAGES = {
    "System Overview": dashboard.render_overview,
    "Process Management and CPU Scheduling": cpu_tab.render,
    "Memory Management": memory_tab.render,
    "Resource Allocation and Deadlocks": deadlock_tab.render,
    "File System and Disk Scheduling": storage_tab.render,
    "Integrated Simulation": simulation_tab.render,
    "Event Log and Metrics": dashboard.render_log,
}
# Pages that show the live integrated simulation (auto-play keeps running on these).
LIVE_PAGES = {"System Overview", "Integrated Simulation", "Event Log and Metrics"}

st.set_page_config(page_title="OSim", layout="wide")
init_state()
simulation_tab.ensure_simulation()

st.sidebar.title("OSim")
st.sidebar.caption("Interactive Operating System Simulation and Visualization Environment")
page = st.sidebar.radio("Section", list(PAGES), key="page")
sim = st.session_state.get("sim")
if sim is not None:
    st.sidebar.divider()
    st.sidebar.write(f"**Integrated simulation**  \ntick {sim.clock} · {sim.status}"
                     + (" · playing" if st.session_state.playing else ""))

PAGES[page]()

# Auto-play: advance the existing simulation by one tick, wait, and redraw.
# Any click interrupts the sleep and re-runs the script, so Pause works immediately.
if st.session_state.playing and sim is not None:
    if page in LIVE_PAGES and sim.can_progress():
        time.sleep(st.session_state.sim_speed)
        sim.step()
        st.rerun()
    else:
        st.session_state.playing = False

"""System Overview page and Event Log and Metrics page."""

import pandas as pd
import streamlit as st

from simulation.process import BLOCKED, STATES
from ui.common import fmt


def render_overview():
    st.header("System Overview")
    sim = st.session_state.get("sim")
    if sim is None:
        st.warning("The integrated simulation could not be built; check its settings.")
        return

    st.subheader(f"Integrated simulation: {st.session_state.sim_scenario}")
    st.caption("Live values from the shared simulation state. Step or run it on the Integrated "
               "Simulation page; the numbers below change with it.")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current tick", sim.clock)
    col2.metric("Status", sim.status)
    col3.metric("Running on CPU", sim.running or "idle")
    col4.metric("Ready queue", " → ".join(sim.ready) or "empty")

    counts = sim.counts_by_state()
    for col, state in zip(st.columns(len(STATES)), STATES):
        col.metric(state, counts[state])

    memory = sim.memory
    metrics = sim.metrics()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Frames in use", f"{memory.used_frames()} / {len(memory.frames)}")
    col2.metric("Page faults", memory.faults)
    col3.metric("Page hits", memory.hits)
    col4.metric("Page-fault ratio", f"{metrics['fault_ratio']:.2f}")

    blocked_io = [p.pid for p in sim.processes.values()
                  if p.state == BLOCKED and (p.blocked_reason or "").startswith("waiting for disk")]
    pending = len(sim.disk["queue"]) + (1 if sim.disk["current"] else 0)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pending disk requests", pending)
    col2.metric("Blocked on I/O", ", ".join(blocked_io) or "none")
    col3.metric("Completed file I/O", sim.io_completed)
    col4.metric("Deadlock", ", ".join(sim.deadlocked) if sim.deadlocked else "none")

    rm = sim.resources
    st.markdown("**Resources**")
    st.dataframe(pd.DataFrame([
        {"Resource": r, "Total": rm.totals[r], "Available": rm.available[r],
         "Allocated": rm.totals[r] - rm.available[r]} for r in rm.names
    ]), hide_index=True)

    st.subheader("Latest standalone results")
    st.caption("These come from the individual algorithm pages and are independent of the "
               "integrated simulation above.")
    ss = st.session_state
    rows = []
    if ss.last_cpu:
        r = ss.last_cpu
        detail = f"avg waiting {fmt(r['result']['avg_waiting'])}, avg turnaround {fmt(r['result']['avg_turnaround'])}"
        if r["quantum"] is not None:
            detail += f", quantum {r['quantum']}"
        rows.append({"Module": "CPU scheduling", "Algorithm": r["algorithm"], "Result": detail})
    if ss.last_paging:
        r = ss.last_paging["result"]
        rows.append({"Module": "Page replacement", "Algorithm": r["algorithm"],
                     "Result": f"{r['faults']} faults, {r['hits']} hits ({ss.last_paging['frames']} frames)"})
    if ss.last_alloc:
        r = ss.last_alloc
        rows.append({"Module": "Memory allocation", "Algorithm": f"{r['strategy']} ({r['mode']})",
                     "Result": f"not allocated: {', '.join(r['unallocated']) or 'none'}"})
    if ss.last_bankers:
        r = ss.last_bankers
        rows.append({"Module": "Banker's algorithm", "Algorithm": "safety check",
                     "Result": "safe: " + " → ".join(f"P{i}" for i in r["sequence"]) if r["safe"] else "unsafe"})
    if "rm" in ss:
        found = ss.rm.detect([p for p in ss.rm.held if p not in ss.rm_terminated])["deadlocked"]
        rows.append({"Module": "Deadlock detection", "Algorithm": "resource manager",
                     "Result": f"deadlocked: {', '.join(found)}" if found else "no deadlock"})
    if ss.last_disk:
        r = ss.last_disk["result"]
        rows.append({"Module": "Disk scheduling", "Algorithm": r["policy"],
                     "Result": f"total head movement {r['total_movement']}"})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    else:
        st.write("No standalone algorithm has been run yet.")


def render_log():
    st.header("Event Log and Metrics")
    sim = st.session_state.get("sim")
    if sim is not None:
        st.subheader("Integrated simulation events")
        events = pd.DataFrame(sim.events)
        col1, col2, col3 = st.columns(3)
        subsystems = col1.multiselect("Subsystem", sorted(events["subsystem"].unique()))
        pid = col2.selectbox("Process", ["All"] + list(sim.processes))
        kinds = col3.multiselect("Event type", sorted(events["event"].unique()))
        shown = events
        if subsystems:
            shown = shown[shown["subsystem"].isin(subsystems)]
        if pid != "All":
            shown = shown[shown["pid"] == pid]
        if kinds:
            shown = shown[shown["event"].isin(kinds)]
        st.caption(f"{len(shown)} of {len(events)} events. 'tick' is the tick in which the event "
                   "happened (deadlock checks happen between ticks and use the next tick).")
        st.dataframe(shown, hide_index=True, height=320)

        st.subheader("Simulation metrics")
        m = sim.metrics()
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Ticks simulated", m["ticks"])
        col2.metric("CPU utilization", f"{m['cpu_utilization']:.0%}")
        col3.metric("Throughput (processes/tick)", fmt(m["throughput"], 3))
        col4.metric("Context switches", m["context_switches"])
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Avg waiting (finished)", fmt(m["avg_waiting"]))
        col2.metric("Avg turnaround (finished)", fmt(m["avg_turnaround"]))
        col3.metric("Avg response", fmt(m["avg_response"]))
        col4.metric("Disk head movement", m["disk_movement"])
        st.dataframe(pd.DataFrame(sim.process_rows()).astype(str), hide_index=True)

    st.subheader("Standalone module activity")
    activity = st.session_state.activity
    if activity:
        st.dataframe(pd.DataFrame(list(reversed(activity))), hide_index=True)
    else:
        st.write("No standalone actions yet.")

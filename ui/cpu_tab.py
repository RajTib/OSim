"""Process Management and CPU Scheduling page (standalone algorithms)."""

import pandas as pd
import streamlit as st

from algorithms.cpu_scheduling import ALGORITHMS, compare_algorithms, run_algorithm
from simulation.process import ALLOWED_TRANSITIONS, STATES
from ui import charts
from ui.common import fmt, is_blank, log_activity, whole_number

SAMPLE_PROCESSES = [
    {"pid": "P1", "arrival": 0, "burst": 5, "priority": 3},
    {"pid": "P2", "arrival": 1, "burst": 3, "priority": 1},
    {"pid": "P3", "arrival": 2, "burst": 1, "priority": 4},
    {"pid": "P4", "arrival": 3, "burst": 2, "priority": 2},
    {"pid": "P5", "arrival": 4, "burst": 3, "priority": 5},
]


def read_processes(table):
    """Turn the editable table into the list of dicts the algorithms expect."""
    processes = []
    for _, row in table.iterrows():
        values = [row["pid"], row["arrival"], row["burst"], row["priority"]]
        if all(is_blank(v) for v in values):
            continue  # empty row left over from "add row"
        if any(is_blank(v) for v in values[:3]):
            raise ValueError("Every row needs a process ID, arrival time and burst time.")
        pid = str(row["pid"]).strip()
        processes.append({
            "pid": pid,
            "arrival": whole_number(row["arrival"], pid, "arrival time"),
            "burst": whole_number(row["burst"], pid, "burst time"),
            "priority": 0 if is_blank(row["priority"]) else whole_number(row["priority"], pid, "priority"),
        })
    return processes


def _show_result(last):
    result = last["result"]
    title = last["algorithm"] + ("" if last["quantum"] is None else f" (quantum = {last['quantum']})")
    st.subheader(f"Result of last run: {title}")
    st.caption("Shows the table as it was when you pressed Run; press Run again after editing.")

    st.markdown("**Gantt chart**")
    st.pyplot(charts.gantt(result["timeline"]))

    col1, col2, col3 = st.columns(3)
    col1.metric("Average waiting time", fmt(result["avg_waiting"]))
    col2.metric("Average turnaround time", fmt(result["avg_turnaround"]))
    col3.metric("Average response time", fmt(result["avg_response"]))
    col1, col2, col3 = st.columns(3)
    col1.metric("CPU utilization", f"{result['cpu_utilization']:.0%}")
    col2.metric("Throughput (processes / unit)", fmt(result["throughput"], 3))
    col3.metric("Context switches", result["context_switches"])

    st.markdown("**Process metrics**")
    st.dataframe(
        pd.DataFrame(result["processes"]).rename(columns={
            "pid": "Process", "arrival": "Arrival", "burst": "Burst", "priority": "Priority",
            "completion": "Completion", "turnaround": "Turnaround", "waiting": "Waiting",
            "response": "Response",
        }),
        hide_index=True,
    )
    with st.expander("Execution timeline (every segment of the Gantt chart)"):
        st.dataframe(pd.DataFrame(
            [{"Process": pid, "Start": s, "End": e, "Length": e - s} for pid, s, e in result["timeline"]]
        ), hide_index=True)


def render():
    st.header("Process Management and CPU Scheduling")
    st.write(
        "Edit the process table (add rows at the bottom, select a row and press Delete to "
        "remove it), choose an algorithm, and run it. A lower priority number means a higher "
        "priority. Make an arrival time larger than the others' finish times to see CPU idle time."
    )

    st.button("Reset to sample data", on_click=lambda: st.session_state.pop("process_editor", None))
    table = st.data_editor(
        pd.DataFrame(SAMPLE_PROCESSES),
        key="process_editor",
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "pid": st.column_config.TextColumn("Process ID"),
            "arrival": st.column_config.NumberColumn("Arrival time", step=1, format="%d"),
            "burst": st.column_config.NumberColumn("Burst time", step=1, format="%d"),
            "priority": st.column_config.NumberColumn("Priority", step=1, format="%d"),
        },
    )

    col_algo, col_quantum = st.columns(2)
    algorithm = col_algo.selectbox("Algorithm", ALGORITHMS, index=ALGORITHMS.index("Round Robin"))
    quantum = col_quantum.number_input("Time quantum (Round Robin only)", value=2, step=1,
                                       disabled=(algorithm != "Round Robin"))

    col_run, col_compare = st.columns(2)
    if col_run.button("Run scheduling simulation", type="primary"):
        try:
            processes = read_processes(table)
            result = run_algorithm(algorithm, processes, int(quantum))
        except ValueError as error:
            st.error(str(error))
        else:
            quantum_used = int(quantum) if algorithm == "Round Robin" else None
            st.session_state.last_cpu = {"algorithm": algorithm, "quantum": quantum_used, "result": result}
            detail = "" if quantum_used is None else f", quantum {quantum_used}"
            log_activity("CPU", "SCHEDULE", f"{algorithm}{detail} on {len(processes)} processes "
                                            f"(avg waiting {result['avg_waiting']:.2f})")

    if col_compare.button("Compare all algorithms on this workload"):
        try:
            rows = compare_algorithms(read_processes(table), int(quantum))
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_cpu_compare = {"quantum": int(quantum), "rows": rows}
            best = min(rows, key=lambda r: r["avg_waiting"])
            log_activity("CPU", "COMPARE", f"compared {len(rows)} algorithms; lowest average "
                                           f"waiting time: {best['algorithm']}")

    if st.session_state.last_cpu is None:
        st.info("Press 'Run scheduling simulation' to see the Gantt chart and results.")
    else:
        _show_result(st.session_state.last_cpu)

    comparison = st.session_state.last_cpu_compare
    if comparison is not None:
        st.subheader(f"Algorithm comparison (Round Robin quantum = {comparison['quantum']})")
        frame = pd.DataFrame(comparison["rows"]).rename(columns={
            "algorithm": "Algorithm", "avg_waiting": "Avg waiting", "avg_turnaround": "Avg turnaround",
            "avg_response": "Avg response", "cpu_utilization": "CPU utilization",
            "throughput": "Throughput", "context_switches": "Context switches", "total_time": "Finish time",
        })
        st.dataframe(frame.style.format({"Avg waiting": "{:.2f}", "Avg turnaround": "{:.2f}",
                                         "Avg response": "{:.2f}", "CPU utilization": "{:.0%}",
                                         "Throughput": "{:.3f}"}), hide_index=True)
        st.bar_chart(frame, x="Algorithm", y=["Avg waiting", "Avg turnaround"], stack=False)

    with st.expander("Process states and the process control block (PCB)"):
        st.write(
            "The integrated simulation keeps a PCB for every process (PID, arrival, priority, "
            "state, program counter, CPU time, waiting/blocked time, page faults, held resources "
            "and what it is waiting for). Only these state changes are allowed; anything else "
            "is rejected by the code:"
        )
        st.dataframe(pd.DataFrame([
            {"From": s, "Allowed next states": ", ".join(sorted(ALLOWED_TRANSITIONS[s])) or "(final)"}
            for s in STATES
        ]), hide_index=True)
        st.caption("The standalone algorithms on this page only need arrival, burst and priority; "
                   "see the Integrated Simulation page for processes moving through these states.")

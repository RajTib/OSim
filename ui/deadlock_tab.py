"""Resource Allocation and Deadlocks page.

Two separate tools, because they are two different ideas:
  * Resource manager + DETECTION: processes request/release resources; deadlocks
    are allowed to happen, then detected and recovered from.
  * Banker's algorithm (AVOIDANCE): with known maximum claims, a request is
    granted only if the system stays in a safe state.
"""

import pandas as pd
import streamlit as st

from algorithms.deadlock import bankers_request, bankers_safety, detect_deadlock
from simulation.resources import ResourceManager, parse_resources
from ui import charts
from ui.common import log_activity, parse_numbers

DEFAULT_RESOURCES = "R1=1, R2=1, R3=2"
DEFAULT_PROCESSES = "P1, P2, P3"

# Banker's textbook example (Silberschatz): resources A, B, C
BANKERS_DEFAULTS = {
    "bk_names": "A B C",
    "bk_available": "3 3 2",
    "bk_max": "7 5 3\n3 2 2\n9 0 2\n2 2 2\n4 3 3",
    "bk_allocation": "0 1 0\n2 0 0\n3 0 2\n2 1 1\n0 0 2",
    "bk_request": "1 0 2",
}


# ------------------------------------------------------------ resource manager + detection

def _parse_pids(text):
    pids = [p.strip() for p in text.replace(" ", ",").split(",") if p.strip()]
    if not pids:
        raise ValueError("Enter at least one process name.")
    if len(set(pids)) != len(pids):
        raise ValueError("Process names must be unique.")
    return pids


def _new_manager(resources_text, processes_text):
    rm = ResourceManager(parse_resources(resources_text))
    for pid in _parse_pids(processes_text):
        rm.add_process(pid)
    return rm


def _circular_wait_example():
    """Build a real deadlock through ordinary requests: P1 and P2 each hold what the other wants."""
    rm = ResourceManager({"R1": 1, "R2": 1, "R3": 2})
    for pid in ("P1", "P2", "P3"):
        rm.add_process(pid)
    rm.request("P1", "R1", 1)
    rm.request("P2", "R2", 1)
    rm.request("P3", "R3", 1)
    rm.request("P1", "R2", 1)  # waits: R2 is held by P2
    rm.request("P2", "R1", 1)  # waits: R1 is held by P1 -> circular wait
    return rm


def _reset_manager(rm, message):
    st.session_state.rm = rm
    st.session_state.rm_terminated = []
    st.session_state.rm_message = ("info", message)


def manager_section():
    if "rm" not in st.session_state:
        _reset_manager(_new_manager(DEFAULT_RESOURCES, DEFAULT_PROCESSES), "Created an empty system.")

    st.write(
        "Define resource types with a number of identical instances, then make processes request "
        "and release them. A request that cannot be satisfied makes the process **wait**. "
        "Deadlock detection runs after every change."
    )
    col_res, col_proc = st.columns(2)
    resources_text = col_res.text_input("Resource types (name=instances)", value=DEFAULT_RESOURCES)
    processes_text = col_proc.text_input("Processes", value=DEFAULT_PROCESSES)
    col_a, col_b = st.columns(2)
    if col_a.button("Create / reset system"):
        try:
            _reset_manager(_new_manager(resources_text, processes_text), "System reset.")
        except ValueError as error:
            st.session_state.rm_message = ("error", str(error))
    if col_b.button("Load circular-wait example"):
        _reset_manager(_circular_wait_example(),
                       "Loaded: P1 holds R1 and requested R2; P2 holds R2 and requested R1; "
                       "P3 holds one R3.")
        log_activity("DEADLOCK", "EXAMPLE", "loaded the circular-wait example")

    rm = st.session_state.rm
    terminated = st.session_state.rm_terminated
    alive = [p for p in rm.held if p not in terminated]

    st.markdown("**Request or release**")
    col_p, col_r, col_c = st.columns(3)
    pid = col_p.selectbox("Process", alive) if alive else None
    resource = col_r.selectbox("Resource", rm.names)
    count = col_c.number_input("Instances", min_value=1, value=1, step=1)
    col_req, col_rel, col_all = st.columns(3)
    try:
        if col_req.button("Request", type="primary", disabled=pid is None):
            granted = rm.request(pid, resource, int(count))
            text = f"{pid} requested {resource} x{count}: " + ("granted." if granted else "must wait.")
            st.session_state.rm_message = ("success" if granted else "warning", text)
            log_activity("DEADLOCK", "REQUEST", text)
        if col_rel.button("Release", disabled=pid is None):
            rm.release(pid, resource, int(count))
            granted = rm.grant_waiting()
            text = f"{pid} released {resource} x{count}."
            if granted:
                text += " Now granted: " + ", ".join(f"{g['pid']} ({g['resource']} x{g['count']})"
                                                     for g in granted)
            st.session_state.rm_message = ("success", text)
            log_activity("DEADLOCK", "RELEASE", text)
        if col_all.button("Release everything held by this process", disabled=pid is None):
            released = rm.release_all(pid)
            granted = rm.grant_waiting()
            st.session_state.rm_message = ("success", f"{pid} released {released or 'nothing'}; "
                                           f"waiting requests granted: {len(granted)}.")
    except ValueError as error:  # invalid accounting is refused by the ResourceManager
        st.session_state.rm_message = ("error", str(error))

    kind, text = st.session_state.rm_message
    getattr(st, kind)(text)

    pids, names, available, allocation, request = rm.matrices()
    left, right = st.columns(2)
    left.markdown("**Resources**")
    left.dataframe(pd.DataFrame([
        {"Resource": r, "Total": rm.totals[r], "Available": rm.available[r],
         "Allocated": rm.totals[r] - rm.available[r]} for r in names
    ]), hide_index=True)
    right.markdown("**Waiting requests (FIFO)**")
    right.dataframe(pd.DataFrame(rm.waiting or [], columns=["pid", "resource", "count"]).rename(
        columns={"pid": "Process", "resource": "Resource", "count": "Instances"}), hide_index=True)
    left, right = st.columns(2)
    left.markdown("**Allocation matrix**")
    left.dataframe(pd.DataFrame(allocation, index=pids, columns=names))
    right.markdown("**Request matrix**")
    right.dataframe(pd.DataFrame(request, index=pids, columns=names))
    if terminated:
        st.caption("Terminated by recovery: " + ", ".join(terminated))

    detection = rm.detect([p for p in pids if p not in terminated])
    st.markdown("**Resource-allocation graph**")
    st.pyplot(charts.resource_graph(pids, names, rm.totals, rm.available, rm.held, rm.waiting,
                                    detection["deadlocked"]))
    st.caption("Black arrow resource → process: the process holds it. Red dashed arrow process → "
               "resource: the process is waiting for it. Red circles are deadlocked.")

    st.markdown("**Deadlock detection**")
    if detection["deadlocked"]:
        st.error("Deadlock: " + ", ".join(detection["deadlocked"]) + " can never continue.")
        for line in detection["explanation"]:
            st.write("- " + line)
        if st.button("Recover: terminate a victim"):
            victims = []
            while True:
                found = rm.detect([p for p in pids if p not in terminated])["deadlocked"]
                if not found:
                    break
                victim = rm.pick_victim(found)
                rm.release_all(victim)
                terminated.append(victim)
                victims.append(victim)
            granted = rm.grant_waiting()
            text = (f"Terminated {', '.join(victims)} (the deadlocked process holding the most "
                    f"resources) and released its resources. Granted afterwards: "
                    + (", ".join(g["pid"] for g in granted) or "none") + ".")
            st.session_state.rm_message = ("success", text)
            log_activity("DEADLOCK", "RECOVERY", text)
            st.rerun()
    else:
        st.success("No deadlock: every process can still finish.")

    with st.expander("How detection decided (work / finish steps)"):
        steps = detect_deadlock(available, allocation, request)["steps"]
        st.write("Processes holding nothing start as finished. Then, repeatedly, a process whose "
                 "current request fits in Work is assumed to finish and return what it holds.")
        st.dataframe(pd.DataFrame([
            {"Process": pids[s["process"]], "Work before": s["work_before"], "Request": s["needs"],
             "Releases": s["releases"], "Work after": s["work_after"]} for s in steps
        ]), hide_index=True)


# ------------------------------------------------------------ Banker's algorithm

def _parse_matrix(text, what):
    rows = [parse_numbers(line, what) for line in text.splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"{what} needs at least one row.")
    return rows


def _bankers_inputs():
    names = st.session_state.bk_names.replace(",", " ").split()
    available = parse_numbers(st.session_state.bk_available, "Available")
    maximum = _parse_matrix(st.session_state.bk_max, "Max")
    allocation = _parse_matrix(st.session_state.bk_allocation, "Allocation")
    if len(names) != len(available):
        raise ValueError("Give one resource name per Available value.")
    if len(maximum) != len(allocation):
        raise ValueError("Max and Allocation must have the same number of rows (one per process).")
    return names, available, maximum, allocation


def _matrix_text(matrix):
    return "\n".join(" ".join(str(v) for v in row) for row in matrix)


def _submit_request():
    """Button callback: runs before the widgets are drawn, so it may update their values."""
    try:
        names, available, maximum, allocation = _bankers_inputs()
        process = int(st.session_state.bk_process[1:])
        request = parse_numbers(st.session_state.bk_request, "Request")
        result = bankers_request(process, request, available, maximum, allocation)
    except ValueError as error:
        st.session_state.bk_request_result = ("error", str(error))
        return
    message = f"P{process} requests {request}: {result['reason']}"
    st.session_state.bk_request_result = ("success" if result["granted"] else "warning", message)
    log_activity("BANKER", "REQUEST", message)
    if result["granted"] and st.session_state.bk_apply:
        st.session_state.bk_available = " ".join(str(v) for v in result["available"])
        st.session_state.bk_allocation = _matrix_text(result["allocation"])


def bankers_section():
    for key, value in BANKERS_DEFAULTS.items():
        st.session_state.setdefault(key, value)
    st.session_state.setdefault("bk_apply", True)
    st.session_state.setdefault("bk_request_result", None)

    st.write(
        "**Avoidance**: every process declares its maximum claim in advance. A request is granted "
        "only if, afterwards, there is still a **safe sequence** in which every process can get "
        "its remaining need and finish. Unlike detection, an unsafe request is refused *before* "
        "a deadlock can form. (Sample data: the Silberschatz textbook example.)"
    )
    if st.button("Load textbook example"):
        for key, value in BANKERS_DEFAULTS.items():
            st.session_state[key] = value
        st.session_state.bk_request_result = None
        st.rerun()

    col_names, col_avail = st.columns(2)
    col_names.text_input("Resource names", key="bk_names")
    col_avail.text_input("Available", key="bk_available")
    col_max, col_alloc = st.columns(2)
    col_max.text_area("Max (one row per process P0, P1, ...)", key="bk_max", height=140)
    col_alloc.text_area("Allocation (one row per process)", key="bk_allocation", height=140)

    try:
        names, available, maximum, allocation = _bankers_inputs()
        safety = bankers_safety(available, maximum, allocation)
    except ValueError as error:
        st.error(str(error))
        return

    labels = [f"P{i}" for i in range(len(allocation))]
    st.markdown("**Need = Max − Allocation**")
    st.dataframe(pd.DataFrame(safety["need"], index=labels, columns=names))
    if safety["safe"]:
        st.success("SAFE. Safe sequence: " + " → ".join(f"P{i}" for i in safety["sequence"]))
    else:
        st.error("UNSAFE: no order lets every process finish. Stuck: "
                 + ", ".join(labels[i] for i in range(len(labels)) if i not in safety["sequence"]))
    with st.expander("Safety algorithm steps"):
        st.dataframe(pd.DataFrame([
            {"Process": f"P{s['process']}", "Work before": s["work_before"], "Need": s["needs"],
             "Releases": s["releases"], "Work after": s["work_after"]} for s in safety["steps"]
        ]), hide_index=True)
    st.session_state.last_bankers = {"safe": safety["safe"], "sequence": safety["sequence"]}

    st.markdown("**Resource request**")
    col_p, col_r, col_apply = st.columns(3)
    if st.session_state.get("bk_process") not in labels:
        st.session_state.bk_process = labels[0]
    col_p.selectbox("Process", labels, key="bk_process")
    col_r.text_input("Request vector", key="bk_request")
    col_apply.checkbox("Apply granted requests to the matrices", key="bk_apply")
    st.button("Submit request (Banker's algorithm)", type="primary", on_click=_submit_request)
    if st.session_state.bk_request_result:
        kind, text = st.session_state.bk_request_result
        getattr(st, kind)(text)


def render():
    st.header("Resource Allocation and Deadlocks")
    tab_detect, tab_bankers = st.tabs(["Resource manager and deadlock detection",
                                       "Banker's algorithm (avoidance)"])
    with tab_detect:
        manager_section()
    with tab_bankers:
        bankers_section()

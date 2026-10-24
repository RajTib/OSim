"""Integrated Simulation page: one shared system state, advanced tick by tick.

The Simulation object lives in st.session_state.sim. Every button below calls
a method on that same object (step, run, recover...), so pressing "Step" really
advances the existing state rather than rebuilding it. "Build / reset" is the
only control that creates a new Simulation.
"""

import pandas as pd
import streamlit as st

from algorithms.cpu_scheduling import ALGORITHMS as SCHEDULERS
from algorithms.disk_scheduling import DIRECTIONS, POLICIES as DISK_POLICIES
from simulation.memory import ONLINE_POLICIES
from simulation.process import format_instruction
from simulation.scenarios import SCENARIOS, build_simulation
from ui import charts

FORMAT_HELP = """
**Workload format** — one process per line: `PID ARRIVAL PRIORITY PAGES : instructions`
(lower priority number = higher priority; PAGES = size of its virtual address space).

| Instruction | Meaning |
|---|---|
| `CPU n` | compute for n ticks |
| `MEM p` | access virtual page p (page fault if not in memory) |
| `REQ name n` / `REL name n` | request / release n instances of a resource |
| `READ /path` | read a file (disk I/O) |
| `WRITE /path text` | append text to a file, creating it if needed (disk I/O) |

**Resources**: `name=instances, ...`  **Files**: one `path = content` per line.
"""

CONFIG_KEYS = {  # widget key -> SimConfig field
    "sim_scheduler": "scheduler", "sim_quantum": "quantum", "sim_frames": "num_frames",
    "sim_page_policy": "page_policy", "sim_fault_ticks": "page_fault_ticks",
    "sim_disk_policy": "disk_policy", "sim_head": "disk_head", "sim_direction": "disk_direction",
    "sim_seek": "seek_rate", "sim_auto": "auto_recover",
}


def load_scenario(name=None):
    ss = st.session_state
    name = name or ss.sim_scenario
    scenario = SCENARIOS[name]
    ss.sim_workload = scenario["workload"]
    ss.sim_resources = scenario["resources"]
    ss.sim_files = scenario["files"]
    config = scenario["config"]
    ss.sim_scheduler = config["scheduler"]
    ss.sim_quantum = config["quantum"]
    ss.sim_frames = config["num_frames"]
    ss.sim_page_policy = config["page_policy"]
    ss.sim_fault_ticks = config["page_fault_ticks"]
    ss.sim_disk_policy = config["disk_policy"]
    ss.sim_head = config["disk_head"]
    ss.sim_direction = "up"
    ss.sim_seek = config["seek_rate"]
    ss.sim_auto = False


def build_from_inputs():
    ss = st.session_state
    values = {field: ss[key] for key, field in CONFIG_KEYS.items()}
    for field in ("quantum", "num_frames", "page_fault_ticks", "disk_head", "seek_rate"):
        values[field] = int(values[field])
    try:
        ss.sim = build_simulation(ss.sim_workload, ss.sim_resources, ss.sim_files, **values)
        ss.sim_error = None
    except ValueError as error:
        ss.sim_error = str(error)
    ss.playing = False


def on_scenario_change():
    load_scenario()
    build_from_inputs()


def ensure_simulation():
    """Create the default scenario on the first run so every page has a simulation to show."""
    ss = st.session_state
    ss.setdefault("sim_scenario", next(iter(SCENARIOS)))
    ss.setdefault("sim_limit", 500)
    ss.setdefault("sim_speed", 0.6)
    ss.setdefault("playing", False)
    ss.setdefault("sim_error", None)
    if "sim_workload" not in ss:
        load_scenario()
    if "sim" not in ss:
        build_from_inputs()


# ------------------------------------------------------------ button callbacks

def step_ticks(n):
    sim = st.session_state.sim
    for _ in range(n):
        if not sim.step():
            break


def run_to_completion():
    st.session_state.sim.run(int(st.session_state.sim_limit))
    st.session_state.playing = False


def toggle_play():
    st.session_state.playing = not st.session_state.playing


def recover():
    st.session_state.sim.recover_deadlock()


# ------------------------------------------------------------ display pieces

def _status_banner(sim):
    if sim.status == "finished":
        st.success(f"All processes terminated at time {sim.clock}.")
    elif sim.status == "deadlocked":
        result = sim.resources.detect(sim.active_pids())
        lines = "\n".join(f"- {line}" for line in result["explanation"])
        others = "" if not sim.can_progress() else " Other processes can still run."
        st.error(f"Deadlock detected among {', '.join(sim.deadlocked)}.{others}\n\n{lines}\n\n"
                 "Use 'Recover from deadlock' to terminate a victim, or Reset.")
    elif sim.status == "stalled":
        st.warning("Nothing can change any more: every remaining process is waiting. "
                   "Inspect the tables below or reset.")


def _memory_view(sim):
    memory = sim.memory
    col1, col2, col3 = st.columns(3)
    col1.metric("Frames used", f"{memory.used_frames()} / {len(memory.frames)}")
    col2.metric("Page hits / faults", f"{memory.hits} / {memory.faults}")
    col3.metric("Pending page-ins", len(sim.page_ins))
    left, right = st.columns(2)
    left.markdown(f"**Physical frames** ({memory.policy} replacement)")
    left.dataframe(pd.DataFrame([
        {"Frame": f, "Process": c["pid"] if c else "-", "Page": c["page"] if c else "-",
         "Loaded at": c["loaded_at"] if c else "-", "Last used": c["last_used"] if c else "-"}
        for f, c in enumerate(memory.frames)
    ]), hide_index=True)
    right.markdown("**Page tables** (virtual page → frame)")
    right.dataframe(pd.DataFrame([
        {"Process": pid, "Page": page,
         "Frame": memory.page_tables[pid].get(page, "not resident")}
        for pid in sim.processes for page in range(memory.num_pages[pid])
    ]).astype(str), hide_index=True, height=260)
    if sim.page_ins:
        st.caption("Page-ins in progress: " + ", ".join(
            f"{op['pid']} page {op['page']} (done at tick {op['done_at']})" for op in sim.page_ins))


def _resource_view(sim):
    rm = sim.resources
    st.dataframe(pd.DataFrame([
        {"Resource": r, "Total": rm.totals[r], "Available": rm.available[r],
         "Held by": ", ".join(f"{p} x{h[r]}" for p, h in rm.held.items() if r in h) or "-",
         "Waiting": ", ".join(f"{w['pid']} x{w['count']}" for w in rm.waiting if w["resource"] == r) or "-"}
        for r in rm.names
    ]), hide_index=True)
    active = sim.active_pids()
    if active:
        st.pyplot(charts.resource_graph(active, rm.names, rm.totals, rm.available,
                                        {p: rm.held[p] for p in active}, rm.waiting, sim.deadlocked))


def _disk_view(sim):
    disk = sim.disk
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Head", disk["head"])
    col2.metric("Direction", disk["direction"])
    col3.metric("Total head movement", disk["movement"])
    col4.metric("Requests completed", disk["completed"])
    current = disk["current"]
    if current:
        req = current["request"]
        st.write(f"**Servicing:** {req['pid']} {req['op']} {req['path']} at cylinder "
                 f"{req['cylinder']} (finishes at tick {current['done_at']})")
    st.markdown(f"**Disk queue** ({sim.config.disk_policy})")
    st.dataframe(pd.DataFrame([
        {"Process": r["pid"], "Operation": r["op"], "File": r["path"], "Cylinder": r["cylinder"],
         "Issued at": r["issued"]} for r in disk["queue"]
    ], columns=["Process", "Operation", "File", "Cylinder", "Issued at"]), hide_index=True)
    if len(disk["path"]) > 1:
        st.pyplot(charts.disk_movement(disk["path"], sim.config.disk_cylinders))
    st.markdown("**Virtual file system**")
    st.dataframe(pd.DataFrame([
        {"Path": e["path"], "Type": e["type"], "Size": e["size"],
         "Blocks": ", ".join(str(b) for b in e["blocks"]) or "-"} for e in sim.vfs.tree()
    ]), hide_index=True)


def render():
    ss = st.session_state
    st.header("Integrated Simulation")
    st.write(
        "One shared system: the CPU scheduler, paged memory, resource manager, file system and "
        "disk all act on the same processes. Each tick runs the documented steps in order "
        "(finish page-ins and disk I/O → admit arrivals → grant resources → start disk request → "
        "schedule → execute one instruction tick → record → check for deadlock)."
    )

    st.selectbox("Scenario", list(SCENARIOS), key="sim_scenario", on_change=on_scenario_change)
    st.caption(SCENARIOS[ss.sim_scenario]["description"])

    with st.expander("Workload, resources, files and settings (edit, then press Build / reset)"):
        st.markdown(FORMAT_HELP)
        st.text_area("Workload", key="sim_workload", height=150)
        col_res, col_files = st.columns([1, 2])
        col_res.text_area("Resources", key="sim_resources", height=100)
        col_files.text_area("Initial files", key="sim_files", height=100)
        col1, col2, col3, col4 = st.columns(4)
        col1.selectbox("CPU scheduler", SCHEDULERS, key="sim_scheduler")
        col2.number_input("Time quantum (RR)", min_value=1, step=1, key="sim_quantum")
        col3.number_input("Physical frames", min_value=1, step=1, key="sim_frames")
        col4.selectbox("Page replacement", ONLINE_POLICIES, key="sim_page_policy",
                       help="Optimal is not available here: it needs every future memory access, "
                            "which the simulation does not know in advance.")
        col1, col2, col3, col4 = st.columns(4)
        col1.number_input("Page-fault service (ticks)", min_value=1, step=1, key="sim_fault_ticks")
        col2.selectbox("Disk policy", DISK_POLICIES, key="sim_disk_policy")
        col3.number_input("Initial head (0-199)", min_value=0, max_value=199, step=1, key="sim_head")
        col4.number_input("Seek rate (cylinders/tick)", min_value=1, step=1, key="sim_seek")
        col1, col2 = st.columns(2)
        col1.selectbox("Initial disk direction", DIRECTIONS, key="sim_direction")
        col2.checkbox("Recover from deadlocks automatically", key="sim_auto")

    st.button("Build / reset simulation with these settings", type="primary", on_click=build_from_inputs)
    if ss.sim_error:
        st.error(f"Could not build the simulation: {ss.sim_error}")
        return
    sim = ss.sim

    col1, col2, col3, col4, col5 = st.columns(5)
    finished = sim.is_finished()
    col1.button("Step 1 tick", on_click=step_ticks, args=(1,), disabled=finished)
    col2.button("Step 5 ticks", on_click=step_ticks, args=(5,), disabled=finished)
    col3.button("Pause" if ss.playing else "Play", on_click=toggle_play,
                disabled=finished or not sim.can_progress())
    col4.button("Run to completion", on_click=run_to_completion, disabled=finished)
    col5.button("Recover from deadlock", on_click=recover, disabled=not sim.deadlocked)
    col_limit, col_speed = st.columns(2)
    col_limit.number_input("Safety limit for 'Run to completion' (ticks)", min_value=1, step=50,
                           key="sim_limit")
    col_speed.slider("Play speed (seconds per tick)", 0.1, 2.0, step=0.1, key="sim_speed")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current tick", sim.clock)
    col2.metric("Status", sim.status)
    col3.metric("Running on CPU", sim.running or "idle")
    col4.metric("Ready queue", " → ".join(sim.ready) or "empty")
    _status_banner(sim)

    st.markdown("**Process control blocks**")
    st.dataframe(pd.DataFrame(sim.process_rows()).astype(str), hide_index=True)

    if sim.clock > 0:
        st.markdown("**Process states over time**")
        st.pyplot(charts.state_timeline(sim.state_history, list(sim.processes)))
        st.markdown("**CPU Gantt chart**")
        st.pyplot(charts.gantt(sim.cpu_segments()))

    tab_mem, tab_res, tab_disk, tab_events, tab_programs = st.tabs(
        ["Memory", "Resources", "Disk and files", "Recent events", "Programs"])
    with tab_mem:
        _memory_view(sim)
    with tab_res:
        _resource_view(sim)
    with tab_disk:
        _disk_view(sim)
    with tab_events:
        recent = list(reversed(sim.events[-25:]))
        st.dataframe(pd.DataFrame(recent), hide_index=True)
        st.caption("Newest first. The full, filterable log is on the Event Log and Metrics page.")
    with tab_programs:
        for pcb in sim.processes.values():
            steps = [("→ " if i == pcb.pc else "") + format_instruction(ins)
                     for i, ins in enumerate(pcb.program)]
            st.write(f"**{pcb.pid}**: " + "; ".join(steps))

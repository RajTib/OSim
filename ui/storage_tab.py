"""File System and Disk Scheduling page."""

import pandas as pd
import streamlit as st

from algorithms.disk_scheduling import DIRECTIONS, POLICIES, compare_policies, parse_requests, schedule
from filesystem.vfs import FileSystemError
from simulation.workload import build_file_system
from ui import charts
from ui.common import log_activity

SAMPLE_FILES = {
    "/home/readme.txt": "Welcome to the OSim virtual file system.",
    "/home/notes/todo.txt": "1. revise scheduling 2. practise Banker's algorithm",
    "/etc/config.ini": "frames=3",
}
OPERATIONS = ["Create directory", "Create file", "Write (overwrite)", "Append", "Read",
              "Rename", "Delete", "List directory"]
SAMPLE_QUEUE = "98, 183, 37, 122, 14, 124, 65, 67"


def _new_fs():
    return build_file_system(SAMPLE_FILES, total_blocks=48, block_size=16)


def _run_operation(fs, operation, path, content, new_name):
    """Perform one file-system operation and return a message (raises FileSystemError)."""
    if operation == "Create directory":
        fs.mkdir(path)
        return f"Created directory {path}", None
    if operation == "Create file":
        fs.create_file(path, content)
        return f"Created {path} using blocks {fs.file_blocks(path)}", None
    if operation == "Write (overwrite)":
        fs.write_file(path, content)
        return f"Wrote {len(content)} characters; blocks now {fs.file_blocks(path)}", None
    if operation == "Append":
        fs.write_file(path, content, append=True)
        return f"Appended {len(content)} characters; blocks now {fs.file_blocks(path)}", None
    if operation == "Read":
        return f"Read {path}", fs.read_file(path)
    if operation == "Rename":
        fs.rename(path, new_name)
        return f"Renamed {path} to {new_name}", None
    if operation == "Delete":
        blocks = fs.stat(path)["blocks"]
        fs.delete(path)
        return f"Deleted {path}" + (f" and freed blocks {blocks}" if blocks else ""), None
    entries = fs.list_dir(path)
    return f"{path} contains {len(entries)} entries", entries


def file_system_section():
    if "vfs" not in st.session_state:
        st.session_state.vfs = _new_fs()
        st.session_state.vfs_message = None
    fs = st.session_state.vfs

    st.write(
        f"A file system that lives only in this app's memory (it never touches your real "
        f"files). The simulated disk has {fs.total_blocks} blocks of {fs.block_size} characters; "
        f"a file gets the lowest-numbered free blocks, which need not be next to each other."
    )
    col_op, col_path = st.columns([1, 2])
    operation = col_op.selectbox("Operation", OPERATIONS)
    path = col_path.text_input("Path", value="/home/readme.txt")
    content = new_name = ""
    if operation in ("Create file", "Write (overwrite)", "Append"):
        content = st.text_area("Content", value="Some text", height=80)
    if operation == "Rename":
        new_name = st.text_input("New name (in the same directory)", value="renamed.txt")

    col_run, col_reset = st.columns(2)
    if col_run.button("Execute", type="primary"):
        try:
            message, output = _run_operation(fs, operation, path.strip(), content, new_name.strip())
        except FileSystemError as error:
            st.session_state.vfs_message = ("error", str(error), None)
        else:
            st.session_state.vfs_message = ("success", message, output)
            log_activity("FILES", operation.upper(), message)
    if col_reset.button("Reset file system"):
        st.session_state.vfs = fs = _new_fs()
        st.session_state.vfs_message = ("info", "File system reset to the sample files.", None)

    if st.session_state.vfs_message:
        kind, message, output = st.session_state.vfs_message
        getattr(st, kind)(message)
        if isinstance(output, str):
            st.code(output or "(empty file)", language=None)
        elif output is not None:
            st.dataframe(pd.DataFrame(output), hide_index=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Used blocks", fs.used_block_count())
    col2.metric("Free blocks", len(fs.free_blocks))
    col3.metric("Files", sum(1 for e in fs.tree() if e["type"] == "file"))
    st.markdown("**Directory tree**")
    st.dataframe(pd.DataFrame([
        {"Path": e["path"], "Type": e["type"], "Size (chars)": e["size"],
         "Blocks": ", ".join(str(b) for b in e["blocks"]) or "-"} for e in fs.tree()
    ]), hide_index=True)
    st.markdown("**Disk block map**")
    st.pyplot(charts.block_map(fs.block_map()))


def disk_section():
    st.write(
        "The disk head must move to each requested cylinder. The policy decides the order, "
        "which changes the total head movement. Rules: SSTF breaks ties towards the lower "
        "cylinder; SCAN/C-SCAN only travel to the disk edge when they have to turn around; "
        "the C-SCAN/C-LOOK return jump is included in the total."
    )
    requests_text = st.text_input("Request queue (cylinders)", value=SAMPLE_QUEUE)
    col1, col2, col3, col4 = st.columns(4)
    disk_size = col1.number_input("Cylinders (0 .. n-1)", value=200, step=1)
    head = col2.number_input("Initial head position", value=53, step=1)
    direction = col3.selectbox("Initial direction", DIRECTIONS,
                               help="Used by SCAN, C-SCAN, LOOK and C-LOOK.")
    policy = col4.selectbox("Policy", POLICIES)

    col_run, col_compare = st.columns(2)
    if col_run.button("Run disk scheduling", type="primary"):
        try:
            result = schedule(policy, parse_requests(requests_text), int(head), int(disk_size), direction)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_disk = {"result": result, "disk_size": int(disk_size),
                                          "direction": direction}
            log_activity("DISK", "SCHEDULE", f"{policy}: total head movement {result['total_movement']}")
    if col_compare.button("Compare all policies"):
        try:
            rows = compare_policies(parse_requests(requests_text), int(head), int(disk_size), direction)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.last_disk_compare = rows

    last = st.session_state.last_disk
    if last is None:
        st.info("Press 'Run disk scheduling' to see the head movement.")
    else:
        result = last["result"]
        st.subheader(f"{result['policy']} (starting {last['direction']})")
        st.metric("Total head movement (cylinders)", result["total_movement"])
        st.write("**Service order:** " + " → ".join(str(c) for c in result["order"]))
        st.write("**Head path:** " + " → ".join(str(c) for c in result["path"]))
        st.pyplot(charts.disk_movement(result["path"], last["disk_size"]))
        with st.expander("Movement step by step"):
            st.dataframe(pd.DataFrame([
                {"From": s["from"], "To": s["to"], "Distance": s["distance"],
                 "Serviced request": "" if s["serviced"] is None else s["serviced"]}
                for s in result["steps"]
            ]), hide_index=True)

    if st.session_state.last_disk_compare is not None:
        st.subheader("Policy comparison")
        frame = pd.DataFrame(st.session_state.last_disk_compare).rename(columns={
            "policy": "Policy", "total_movement": "Total movement", "order": "Service order"})
        st.dataframe(frame, hide_index=True)
        st.bar_chart(frame, x="Policy", y="Total movement")


def render():
    st.header("File System and Disk Scheduling")
    tab_fs, tab_disk = st.tabs(["Virtual file system", "Disk scheduling"])
    with tab_fs:
        file_system_section()
    with tab_disk:
        disk_section()

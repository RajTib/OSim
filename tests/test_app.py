"""Smoke tests for the Streamlit interface, using Streamlit's headless AppTest.

They check that every page renders without errors and that the main controls
really change what is displayed. (They do not check visual layout.)
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


@pytest.fixture
def at():
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    assert not app.exception
    return app


def open_page(at, name):
    at.sidebar.radio[0].set_value(name).run()
    assert not at.exception, [e.value for e in at.exception]


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.value for e in at.exception]


def metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def widget(elements, label):
    return next(e for e in elements if e.label == label)


def test_every_page_renders(at):
    for page in at.sidebar.radio[0].options:
        open_page(at, page)
        assert not at.error, (page, [e.value for e in at.error])


def test_cpu_page_runs_and_compares(at):
    open_page(at, "Process Management and CPU Scheduling")
    widget(at.selectbox, "Algorithm").set_value("FCFS").run()
    click(at, "Run scheduling simulation")
    # Sample data with FCFS: WT 0, 4, 6, 6, 7 -> 23/5
    assert metric(at, "Average waiting time") == "4.60"
    click(at, "Compare all algorithms on this workload")
    assert any("comparison" in s.value for s in at.subheader)


def test_memory_page_page_replacement_and_allocation(at):
    open_page(at, "Memory Management")
    widget(at.radio, "Algorithm").set_value("LRU").run()
    click(at, "Run page replacement")
    assert metric(at, "Page faults") == "12"
    click(at, "Allocate memory")
    assert metric(at, "Not allocated") == "P4"  # First Fit, variable partitions


def test_deadlock_page_detects_and_recovers(at):
    open_page(at, "Resource Allocation and Deadlocks")
    click(at, "Load circular-wait example")
    assert any("Deadlock: P1, P2" in e.value for e in at.error)
    click(at, "Recover: terminate a victim")
    assert any("Terminated P1" in s.value for s in at.success)
    assert any("No deadlock" in s.value for s in at.success)
    # Banker's tab is on the same page
    assert any("Safe sequence: P1 → P3 → P4 → P0 → P2" in s.value for s in at.success)


def test_bankers_request(at):
    open_page(at, "Resource Allocation and Deadlocks")
    widget(at.selectbox, "Process").set_value("P1").run()  # first 'Process' box is the manager's
    bankers_process = [s for s in at.selectbox if s.label == "Process"][1]
    bankers_process.set_value("P1").run()
    click(at, "Submit request (Banker's algorithm)")
    assert any("Granted" in s.value for s in at.success)


def test_storage_page(at):
    open_page(at, "File System and Disk Scheduling")
    widget(at.selectbox, "Operation").set_value("Create file").run()
    widget(at.text_input, "Path").set_value("/home/new.txt").run()
    click(at, "Execute")
    assert any("Created /home/new.txt" in s.value for s in at.success)
    click(at, "Run disk scheduling")
    assert metric(at, "Total head movement (cylinders)") == "640"  # FCFS textbook example


def test_integrated_simulation_controls(at):
    open_page(at, "Integrated Simulation")
    assert metric(at, "Current tick") == "0"
    click(at, "Step 1 tick")
    assert metric(at, "Current tick") == "1"
    click(at, "Step 5 ticks")
    assert metric(at, "Current tick") == "6"
    click(at, "Run to completion")
    assert metric(at, "Status") == "finished"
    click(at, "Build / reset simulation with these settings")
    assert metric(at, "Current tick") == "0"


def test_integrated_deadlock_scenario_and_overview(at):
    open_page(at, "Integrated Simulation")
    widget(at.selectbox, "Scenario").set_value("Deadlock and recovery").run()
    click(at, "Run to completion")
    assert metric(at, "Status") == "deadlocked"
    click(at, "Recover from deadlock")
    click(at, "Run to completion")
    assert metric(at, "Status") == "finished"

    open_page(at, "System Overview")
    assert metric(at, "Status") == "finished"
    assert metric(at, "Terminated") == "3"


def test_invalid_workload_shows_error(at):
    open_page(at, "Integrated Simulation")
    widget(at.text_area, "Workload").set_value("P1 0 0 1 : FLY 3").run()
    click(at, "Build / reset simulation with these settings")
    assert any("unknown instruction" in e.value for e in at.error)

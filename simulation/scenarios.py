"""Built-in integrated scenarios, written in the same text format the user can edit.

Each scenario is real input for the engine (nothing is scripted or animated):
the events you see come from simulating these programs.
"""

from simulation.engine import SimConfig, Simulation
from simulation.resources import parse_resources
from simulation.workload import parse_files, parse_workload


def _padding(n):
    return "#" * n


SCENARIOS = {
    "All subsystems together": {
        "description": (
            "Five processes share the CPU (Round Robin). P1 and P5 page-fault and wait for "
            "page-ins (3 frames are shared, so pages get evicted). P2 takes the only printer and "
            "P3 blocks until P2 releases it. P4 and P5 read and write files, so they wait for "
            "the disk."
        ),
        "workload": (
            "# PID ARRIVAL PRIORITY PAGES : instructions\n"
            "P1 0 2 4 : CPU 2; MEM 0; MEM 1; CPU 1; MEM 0; MEM 2; CPU 1\n"
            "P2 1 1 2 : CPU 1; REQ printer 1; CPU 3; REL printer 1; CPU 1\n"
            "P3 2 1 2 : CPU 1; REQ printer 1; CPU 1; REL printer 1\n"
            "P4 3 3 2 : CPU 1; READ /data/input.txt; CPU 1; WRITE /logs/app.log P4 finished; CPU 1\n"
            "P5 4 2 3 : MEM 0; READ /data/report.txt; MEM 1; CPU 1\n"
        ),
        "resources": "printer=1",
        "files": (
            "/data/input.txt = Sensor readings: 12 15 11 19 22 18\n"
            f"/data/archive.dat = {_padding(200)}\n"
            "/logs/app.log = boot ok;\n"
            "/data/report.txt = Quarterly report draft\n"
        ),
        "config": {"scheduler": "Round Robin", "quantum": 2, "num_frames": 3,
                   "page_policy": "FIFO", "page_fault_ticks": 2, "disk_policy": "SSTF",
                   "disk_head": 100, "seek_rate": 50},
    },
    "Deadlock and recovery": {
        "description": (
            "P1 takes resource A and P2 takes resource B; then each asks for the other's "
            "resource. Neither can continue: a circular wait. The engine detects the deadlock "
            "while P3 keeps running. Press 'Recover from deadlock' (or enable automatic recovery) "
            "to terminate a victim and let the other process finish."
        ),
        "workload": (
            "# PID ARRIVAL PRIORITY PAGES : instructions\n"
            "P1 0 1 1 : REQ A 1; CPU 2; REQ B 1; CPU 1; REL B 1; REL A 1\n"
            "P2 0 1 1 : REQ B 1; CPU 2; REQ A 1; CPU 1; REL A 1; REL B 1\n"
            "P3 1 2 1 : CPU 6\n"
        ),
        "resources": "A=1, B=1",
        "files": "",
        "config": {"scheduler": "Round Robin", "quantum": 2, "num_frames": 3,
                   "page_policy": "FIFO", "page_fault_ticks": 2, "disk_policy": "FCFS",
                   "disk_head": 0, "seek_rate": 50},
    },
    "Disk scheduling under load": {
        "description": (
            "Five processes read five files that sit on very different cylinders, so several "
            "disk requests queue up at once. Change the disk policy, rebuild and compare the "
            "total head movement and the finishing times."
        ),
        "workload": (
            "# PID ARRIVAL PRIORITY PAGES : instructions\n"
            "P1 0 1 1 : CPU 1; READ /disk/e.txt; CPU 1\n"
            "P2 0 1 1 : CPU 1; READ /disk/a.txt; CPU 1\n"
            "P3 1 1 1 : CPU 1; READ /disk/d.txt; CPU 1\n"
            "P4 1 1 1 : CPU 1; READ /disk/b.txt; CPU 1\n"
            "P5 2 1 1 : CPU 1; READ /disk/c.txt; CPU 1\n"
        ),
        "resources": "printer=1",
        # Padding files push the small files onto different parts of the disk.
        "files": (
            "/disk/a.txt = file A\n"
            f"/disk/pad1.bin = {_padding(160)}\n"
            "/disk/b.txt = file B\n"
            f"/disk/pad2.bin = {_padding(320)}\n"
            "/disk/c.txt = file C\n"
            f"/disk/pad3.bin = {_padding(240)}\n"
            "/disk/d.txt = file D\n"
            f"/disk/pad4.bin = {_padding(160)}\n"
            "/disk/e.txt = file E\n"
        ),
        "config": {"scheduler": "FCFS", "quantum": 2, "num_frames": 3,
                   "page_policy": "FIFO", "page_fault_ticks": 2, "disk_policy": "SSTF",
                   "disk_head": 100, "seek_rate": 20},
    },
}


def build_simulation(workload_text, resources_text, files_text, **config_values):
    """Parse the three text inputs and create a fresh Simulation."""
    config = SimConfig(resources=parse_resources(resources_text), **config_values)
    return Simulation(config, parse_workload(workload_text), parse_files(files_text))


def build_scenario(name, **overrides):
    scenario = SCENARIOS[name]
    values = dict(scenario["config"])
    values.update(overrides)
    return build_simulation(scenario["workload"], scenario["resources"], scenario["files"], **values)

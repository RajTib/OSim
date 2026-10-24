# OSim: Interactive Operating System Simulation and Visualization Environment

An educational Streamlit app for core Operating Systems topics. Each topic has a
standalone visualizer, and an **integrated simulation** runs processes on one
shared simulated system (CPU, paged memory, resources, file system and disk)
tick by tick.

This is a teaching simulator. It does not run real programs and never touches
the host computer's files: processes are short scripts of simulated
instructions, and the file system lives only in memory.

## Setup and run

Requires Python 3 (developed and tested on Python 3.14).

```
pip install -r requirements.txt
streamlit run app.py
```

Streamlit prints a local address (normally http://localhost:8501). Use the sidebar to switch sections.

Run the tests:

```
python -m pytest
```

## What is implemented

| Section | Features |
|---|---|
| **Process Management and CPU Scheduling** | FCFS, SJF (non-preemptive), SRTF, Priority (non-preemptive and preemptive), Round Robin (configurable quantum). Editable process table with sample data, Gantt chart, execution timeline, completion/turnaround/waiting/response times, CPU utilization, throughput, context switches, comparison of all algorithms on the same workload. PCB state-transition table. |
| **Memory Management** | Page replacement: FIFO, LRU, Optimal, with frame contents after every reference, hit/fault, evicted page, totals, fault ratio and a comparison. Contiguous allocation: First/Best/Worst Fit with variable or fixed partitions, a memory-layout chart, and internal/external fragmentation. A table explaining paging vs. contiguous allocation. |
| **Resource Allocation and Deadlocks** | Interactive resource manager (request, release, waiting queue, invalid operations refused), allocation/request matrices, resource-allocation graph, deadlock detection with an explanation of who holds/waits for what, recovery by terminating a victim. Separately: Banker's safety algorithm (safe sequence, steps) and request algorithm (grant / wait / deny as unsafe). |
| **File System and Disk Scheduling** | In-memory file system: directories, create/read/write/append/rename/delete/list, block allocation and release, block map, clear errors. Disk scheduling: FCFS, SSTF, SCAN, C-SCAN, LOOK, C-LOOK with configurable queue, head, cylinders and direction; head path, service order, total movement, chart, comparison. |
| **Integrated Simulation** | Built-in scenarios (editable): all subsystems together, deadlock and recovery, disk scheduling under load. Step 1 / 5 ticks, Play/Pause, Run to completion (with a safety limit), Build/Reset, Recover from deadlock. Shows PCBs, ready queue, process-state timeline, CPU Gantt chart, frames and page tables, resources and graph, disk queue and head path, file system, recent events. |
| **System Overview** | Live values from the integrated simulation (tick, process counts by state, CPU process, ready queue, frames, page faults/hits, resources, pending disk requests, blocked/completed I/O, deadlock status) plus the latest standalone results. |
| **Event Log and Metrics** | Every simulation event (tick, subsystem, process, event type, details) with filters; simulation metrics and per-process results; log of standalone actions. |

## The integrated simulation model

`simulation/engine.py` holds **one `Simulation` object** containing the clock,
PCBs, ready queue, CPU state, paged memory and page tables, resource manager,
virtual file system, disk queue, pending page-ins and the event log. The
Streamlit page keeps this object in session state, and every button calls a
method on it (so "Step" advances the existing state).

**Processes** are scripts, one per line:
`PID ARRIVAL PRIORITY PAGES : instructions`

| Instruction | What happens |
|---|---|
| `CPU n` | uses the CPU for n ticks |
| `MEM p` | hit if page p is resident; otherwise a **page fault** blocks the process until the page-in finishes, then the page table and frames are updated (FIFO or LRU replacement, global) |
| `REQ r n` | granted if n instances of r are free; otherwise the process **blocks** until another process releases them |
| `REL r n` | releases instances; waiting requests are reconsidered next tick |
| `READ /path`, `WRITE /path text` | checked against the file system, turned into a **disk request**; the process blocks until the disk (using the chosen disk policy) services it, then the file system is updated |

States: New → Ready → Running → (Ready | Blocked | Terminated), Blocked → (Ready | Terminated).
Any other transition raises an error.

**Order of work in one tick** (documented in `engine.py`):
1. finish page-ins due now, 2. finish the disk request if done, 3. admit arrivals,
4. grant waiting resource requests, 5. start the next disk request,
6. preempt/dispatch according to the CPU scheduler, 7. execute one tick of the running
process's instruction, 8. record states and metrics, 9. advance the clock,
10. deadlock detection (optionally automatic recovery).

A deadlock never freezes the app: detection runs every tick, "Run to completion"
stops when nothing can change, and the page explains which processes are stuck.

## Algorithm notes and tie-breaking rules

- **Metrics**: turnaround = completion − arrival; waiting = turnaround − burst; response = first run − arrival.
  CPU utilization = busy time / time of the last completion. A context switch is counted when the CPU starts
  a process different from the one that ran last.
- **Ties**: FCFS by arrival then input order. SJF by burst, then arrival, then input order. SRTF and
  preemptive Priority preempt only for a *strictly* better process. Priority: lower number = higher priority.
  Round Robin: a process arriving when a quantum ends is queued before the preempted process.
- **Optimal** page replacement: if several pages are never used again, the one loaded first is evicted.
- **Memory allocation**: ties go to the lowest block. External fragmentation is the total free memory when a
  waiting request would fit in that total but not in any single block.
- **Banker's / detection**: processes are scanned in index order in repeated passes (gives the textbook
  safe sequence P1, P3, P4, P0, P2). Recovery terminates the deadlocked process holding the most instances.
- **Disk**: SSTF ties go to the lower cylinder; SCAN/C-SCAN go to the edge only when they must turn or jump;
  C-SCAN/C-LOOK totals include the return jump.

## Limitations

- Single CPU; one simulated instruction per tick; no real code is executed.
- Page-ins take a fixed number of ticks and run in parallel; they do not go through the disk queue.
  The integrated simulation supports FIFO and LRU only, because Optimal needs every future memory access.
- One disk request per file operation, aimed at the file's first block (or the first free block for a new file).
- SJF/SRTF in the integrated simulation use the remaining length of the process script, which a real OS
  could not know.
- The standalone resource manager, Banker's tool, file system and disk visualizer are separate from the
  integrated simulation (each has its own state).
- Everything is kept in the browser session; reloading the page resets it.

## Project structure

```
app.py                         page setup, sidebar navigation, auto-play loop
algorithms/                    pure algorithm functions (no Streamlit)
  cpu_scheduling.py            FCFS, SJF, SRTF, Priority, Round Robin, metrics, comparison
  page_replacement.py          FIFO, LRU, Optimal
  memory_allocation.py         First/Best/Worst Fit, fragmentation
  deadlock.py                  detection, explanation, recovery, Banker's safety and request
  disk_scheduling.py           FCFS, SSTF, SCAN, C-SCAN, LOOK, C-LOOK
filesystem/vfs.py              in-memory file system with block allocation
simulation/
  process.py                   PCB, states, allowed transitions, instruction format
  memory.py                    physical frames and per-process page tables
  resources.py                 resource manager (ownership, waiting queue, accounting checks)
  workload.py                  parsing and validation of the workload / files text
  engine.py                    the shared state and the tick-by-tick engine
  scenarios.py                 built-in scenarios
ui/                            one file per page, plus charts.py and common.py
tests/                         pytest tests for every module, the engine and the UI
```

## Tests

`tests/` contains tests whose expected values are textbook examples or were traced by hand (the working is
in comments), for example the Silberschatz SJF/SRTF/Priority workloads, the 20-reference page sequence
(FIFO 15 / LRU 12 / Optimal 9 faults), Belady's anomaly, the First/Best/Worst Fit example, the Banker's and
detection matrices, and the 98 183 37 122 14 124 65 67 disk queue for all six policies. The engine is tested
tick by tick for page faults, resource waits, file I/O, deadlock detection and recovery, invariants on every
tick, and determinism; CPU-only workloads must give exactly the same schedule as the standalone algorithms.
`tests/test_app.py` drives the Streamlit pages headlessly with Streamlit's AppTest (it checks behaviour,
not visual layout).

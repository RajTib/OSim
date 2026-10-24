"""Matplotlib charts used by the UI. Every function returns a Figure built from real results.

matplotlib.figure.Figure is used directly (not pyplot) so figures are not kept
in a global list between Streamlit re-runs.
"""

import matplotlib
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch

IDLE = "Idle"
STATE_COLOURS = {
    "New": "#eeeeee", "Ready": "#fff176", "Running": "#81c784",
    "Blocked": "#e57373", "Terminated": "#9e9e9e",
}


def _palette(names):
    colours = matplotlib.colormaps["Pastel1"].colors + matplotlib.colormaps["Pastel2"].colors
    return {name: colours[i % len(colours)] for i, name in enumerate(names)}


def _clean_axes(ax, keep_left=False):
    for side in ("top", "right") if keep_left else ("top", "left", "right"):
        ax.spines[side].set_visible(False)


def gantt(timeline):
    """One horizontal bar; one box per (pid, start, end) segment, grey for idle time."""
    pids = []
    for pid, _, _ in timeline:
        if pid != IDLE and pid not in pids:
            pids.append(pid)
    colour = _palette(pids)

    fig = Figure(figsize=(10, 1.9))
    ax = fig.subplots()
    for pid, start, end in timeline:
        face = "#e0e0e0" if pid == IDLE else colour[pid]
        ax.barh(0, end - start, left=start, height=0.7, color=face, edgecolor="black")
        ax.text((start + end) / 2, 0, pid, ha="center", va="center", fontsize=9)

    marks = sorted({t for _, start, end in timeline for t in (start, end)})
    ax.set_xticks(marks)
    ax.set_xlim(0, marks[-1])
    ax.set_ylim(-0.6, 0.6)
    ax.set_yticks([])
    ax.set_xlabel("Time")
    _clean_axes(ax)
    fig.tight_layout()
    return fig


def memory_layout(blocks):
    """One row per memory block, split into the processes placed in it and free space."""
    pids = [pid for b in blocks for pid, _ in b["segments"]]
    colour = _palette(pids)
    largest = max(b["size"] for b in blocks)

    fig = Figure(figsize=(10, 0.55 * len(blocks) + 0.8))
    ax = fig.subplots()
    for row, b in enumerate(blocks):
        left = 0
        for pid, size in b["segments"]:
            ax.barh(row, size, left=left, height=0.6, color=colour[pid], edgecolor="black")
            ax.text(left + size / 2, row, f"{pid} ({size})", ha="center", va="center", fontsize=8)
            left += size
        if b["free"]:
            ax.barh(row, b["free"], left=left, height=0.6, color="white", edgecolor="black",
                    hatch="//")
            ax.text(left + b["free"] / 2, row, f"free {b['free']}", ha="center", va="center",
                    fontsize=8, backgroundcolor="white")
    ax.set_yticks(range(len(blocks)))
    ax.set_yticklabels([f"Block {b['block'] + 1} ({b['size']})" for b in blocks])
    ax.invert_yaxis()
    ax.set_xlim(0, largest)
    ax.set_xlabel("Memory units")
    _clean_axes(ax, keep_left=True)
    fig.tight_layout()
    return fig


def resource_graph(processes, resources, totals, available, held, waiting, deadlocked=()):
    """Resource-allocation graph.

    Circles are processes (top row), squares are resource types (bottom row).
    Solid black arrow resource -> process = assignment (process holds it).
    Dashed red arrow process -> resource = request (process is waiting for it).
    Deadlocked processes are drawn with a red border.
    """
    n_cols = max(len(processes), len(resources), 1)
    fig = Figure(figsize=(max(6, 1.6 * n_cols), 3.4))
    ax = fig.subplots()

    def x_positions(count):
        step = n_cols / max(count, 1)
        return [step * (i + 0.5) for i in range(count)]

    p_pos = {p: (x, 2.0) for p, x in zip(processes, x_positions(len(processes)))}
    r_pos = {r: (x, 0.0) for r, x in zip(resources, x_positions(len(resources)))}

    for p, (x, y) in p_pos.items():
        red = p in deadlocked
        ax.add_patch(matplotlib.patches.Circle((x, y), 0.32, facecolor="#bbdefb",
                                               edgecolor="#c62828" if red else "black",
                                               linewidth=2.5 if red else 1))
        ax.text(x, y, p, ha="center", va="center", fontsize=9)
    for r, (x, y) in r_pos.items():
        ax.add_patch(matplotlib.patches.Rectangle((x - 0.4, y - 0.3), 0.8, 0.6,
                                                  facecolor="#ffe0b2", edgecolor="black"))
        ax.text(x, y + 0.05, r, ha="center", va="center", fontsize=9)
        ax.text(x, y - 0.5, f"{available[r]}/{totals[r]} free", ha="center", va="center", fontsize=8)

    def arrow(start, end, colour, style, label):
        patch = FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14, color=colour,
                                linestyle=style, linewidth=1.4, shrinkA=16, shrinkB=16)
        ax.add_patch(patch)
        if label:
            ax.text((start[0] + end[0]) / 2, (start[1] + end[1]) / 2, label, fontsize=8,
                    color=colour, backgroundcolor="white")

    for p, holdings in held.items():
        for r, count in holdings.items():
            if p in p_pos and r in r_pos:
                arrow(r_pos[r], p_pos[p], "black", "-", f"x{count}" if count > 1 else "")
    for w in waiting:
        if w["pid"] in p_pos and w["resource"] in r_pos:
            arrow(p_pos[w["pid"]], r_pos[w["resource"]], "#c62828", "--",
                  f"x{w['count']}" if w["count"] > 1 else "")

    ax.set_xlim(-0.2, n_cols + 0.2)
    ax.set_ylim(-0.9, 2.6)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    return fig


def disk_movement(path, disk_size, title=None):
    """Head position (x) against service step (y, going down), like textbook disk diagrams."""
    fig = Figure(figsize=(10, 0.35 * len(path) + 1.2))
    ax = fig.subplots()
    steps = list(range(len(path)))
    ax.plot(path, steps, marker="o", color="#1565c0")
    for cylinder, step in zip(path, steps):
        ax.annotate(str(cylinder), (cylinder, step), textcoords="offset points", xytext=(6, -3),
                    fontsize=8)
    ax.set_xlim(-2, disk_size + 1)
    ax.invert_yaxis()
    ax.set_xlabel("Cylinder")
    ax.set_ylabel("Step")
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")
    if title:
        ax.set_title(title, fontsize=10, pad=24)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return fig


def state_timeline(history, pids):
    """One row per process, one cell per tick, coloured by the process state in that tick."""
    ticks = len(history)
    fig = Figure(figsize=(10, 0.45 * len(pids) + 1.1))
    ax = fig.subplots()
    for row, pid in enumerate(pids):
        for tick, states in enumerate(history):
            ax.barh(row, 1, left=tick, height=0.8, color=STATE_COLOURS[states[pid]],
                    edgecolor="white", linewidth=0.5)
    ax.set_yticks(range(len(pids)))
    ax.set_yticklabels(pids)
    ax.invert_yaxis()
    ax.set_xlim(0, max(ticks, 1))
    ax.set_xlabel("Tick")
    ax.xaxis.get_major_locator().set_params(integer=True)
    handles = [matplotlib.patches.Patch(color=c, label=s) for s, c in STATE_COLOURS.items()]
    ax.legend(handles=handles, ncol=5, fontsize=8, loc="lower center",
              bbox_to_anchor=(0.5, 1.0), frameon=False)
    _clean_axes(ax, keep_left=True)
    fig.tight_layout()
    return fig


def block_map(owners, columns=16):
    """Grid of disk blocks; each file gets a colour, free blocks are white."""
    files = [o for o in dict.fromkeys(owners) if o is not None]
    colour = _palette(files)
    rows = (len(owners) + columns - 1) // columns

    fig = Figure(figsize=(10, 0.45 * rows + 0.9))
    ax = fig.subplots()
    for i, owner in enumerate(owners):
        r, c = divmod(i, columns)
        ax.add_patch(matplotlib.patches.Rectangle((c, -r), 0.95, 0.9,
                                                  facecolor="white" if owner is None else colour[owner],
                                                  edgecolor="#757575"))
        ax.text(c + 0.47, -r + 0.45, str(i), ha="center", va="center", fontsize=7)
    ax.set_xlim(0, columns)
    ax.set_ylim(-rows + 0.9, 1)
    ax.set_aspect("equal")
    ax.axis("off")
    if files:
        handles = [matplotlib.patches.Patch(color=colour[f], label=f) for f in files]
        ax.legend(handles=handles, fontsize=7, loc="upper left", bbox_to_anchor=(1.0, 1.0),
                  frameon=False)
    fig.tight_layout()
    return fig

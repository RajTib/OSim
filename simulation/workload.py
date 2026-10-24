"""Parsing and validating the text formats used to configure the integrated simulation.

Workload: one process per line, '#' starts a comment.

    PID ARRIVAL PRIORITY PAGES : INSTRUCTION; INSTRUCTION; ...

    P1 0 2 3 : CPU 2; MEM 0; REQ printer 1; CPU 1; REL printer 1
    P2 1 1 2 : READ /data/in.txt; WRITE /data/out.txt result=42; CPU 1

Files: one file per line, 'path = content'. Directories are created as needed.

    /data/in.txt = hello world
"""

from filesystem.vfs import VirtualFileSystem
from simulation.process import OPCODES


def _int(token, what, line_no):
    try:
        return int(token)
    except ValueError:
        raise ValueError(f"Line {line_no}: {what} must be a whole number, got {token!r}.") from None


def parse_instruction(text, line_no):
    parts = text.split()
    op = parts[0].upper()
    if op not in OPCODES:
        raise ValueError(f"Line {line_no}: unknown instruction {parts[0]!r} "
                         f"(use {', '.join(OPCODES)}).")
    args = parts[1:]
    if op in ("CPU", "MEM"):
        if len(args) != 1:
            raise ValueError(f"Line {line_no}: {op} needs exactly one number.")
        return (op, _int(args[0], f"{op} argument", line_no))
    if op in ("REQ", "REL"):
        if len(args) != 2:
            raise ValueError(f"Line {line_no}: {op} needs a resource name and a count.")
        return (op, args[0], _int(args[1], f"{op} count", line_no))
    if op == "READ":
        if len(args) != 1:
            raise ValueError(f"Line {line_no}: READ needs one file path.")
        return (op, args[0])
    # WRITE path text...
    if len(args) < 2:
        raise ValueError(f"Line {line_no}: WRITE needs a file path and some text.")
    return (op, args[0], " ".join(args[1:]))


def parse_workload(text):
    """Return a list of process specs {pid, arrival, priority, pages, program}."""
    processes = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"Line {line_no}: expected 'PID ARRIVAL PRIORITY PAGES : instructions'.")
        header, body = line.split(":", 1)
        fields = header.split()
        if len(fields) != 4:
            raise ValueError(f"Line {line_no}: expected 'PID ARRIVAL PRIORITY PAGES' before ':'.")
        program = [parse_instruction(part.strip(), line_no)
                   for part in body.split(";") if part.strip()]
        processes.append({
            "pid": fields[0],
            "arrival": _int(fields[1], "arrival", line_no),
            "priority": _int(fields[2], "priority", line_no),
            "pages": _int(fields[3], "pages", line_no),
            "program": program,
        })
    return processes


def parse_files(text):
    """Return {path: content} from 'path = content' lines."""
    files = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Files line {line_no}: expected 'path = content'.")
        path, content = line.split("=", 1)
        files[path.strip()] = content.strip()
    return files


def validate_workload(processes, resource_totals):
    """Check a workload before simulating it.

    Because each program is a straight list of instructions, resource use can
    be checked statically: a process may never hold more instances than exist
    and may never release instances it does not hold.
    """
    if not processes:
        raise ValueError("The workload needs at least one process.")
    seen = set()
    for p in processes:
        pid = p["pid"]
        if pid in seen:
            raise ValueError(f"Duplicate process ID: {pid}.")
        seen.add(pid)
        if p["arrival"] < 0:
            raise ValueError(f"{pid}: arrival time cannot be negative.")
        if p["priority"] < 0:
            raise ValueError(f"{pid}: priority cannot be negative.")
        if p["pages"] <= 0:
            raise ValueError(f"{pid}: number of pages must be greater than 0.")
        if not p["program"]:
            raise ValueError(f"{pid}: program has no instructions.")

        held = {}
        for instruction in p["program"]:
            op = instruction[0]
            if op == "CPU" and instruction[1] <= 0:
                raise ValueError(f"{pid}: CPU burst must be greater than 0.")
            if op == "MEM" and not 0 <= instruction[1] < p["pages"]:
                raise ValueError(f"{pid}: MEM {instruction[1]} is outside pages 0..{p['pages'] - 1}.")
            if op in ("REQ", "REL"):
                _, resource, count = instruction
                if resource not in resource_totals:
                    raise ValueError(f"{pid}: unknown resource {resource!r}.")
                if count <= 0:
                    raise ValueError(f"{pid}: {op} count must be greater than 0.")
                now = held.get(resource, 0)
                if op == "REQ" and now + count > resource_totals[resource]:
                    raise ValueError(f"{pid}: would hold {now + count} {resource}, "
                                     f"but only {resource_totals[resource]} exist.")
                if op == "REL" and count > now:
                    raise ValueError(f"{pid}: releases {count} {resource} but holds only {now}.")
                held[resource] = now + count if op == "REQ" else now - count
            if op in ("READ", "WRITE") and not instruction[1].startswith("/"):
                raise ValueError(f"{pid}: file paths must be absolute (start with '/').")


def build_file_system(files, total_blocks, block_size):
    """Create a VirtualFileSystem holding the given {path: content} files."""
    vfs = VirtualFileSystem(total_blocks, block_size)
    for path, content in files.items():
        parts = path.strip("/").split("/")
        for depth in range(1, len(parts)):
            directory = "/" + "/".join(parts[:depth])
            if not vfs.exists(directory):
                vfs.mkdir(directory)
        vfs.create_file(path, content)
    return vfs

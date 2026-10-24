"""Paged physical memory shared by all processes in the integrated simulation.

    * Physical memory is a list of frames. A frame holds one (pid, page) or is free.
    * Every process has a page table: {virtual page: frame number} for its
      resident pages. A page that is not in the table is not in memory.
    * access()  -> hit if the page is resident (updates its "last used" time).
    * load()    -> called when a page-in finishes; uses a free frame or evicts a
                   victim chosen by the replacement policy, updating BOTH the
                   victim's and the new owner's page tables.

Replacement here is GLOBAL (a process may evict another process's page) and
supports FIFO and LRU only. Optimal needs to know every future memory access of
every process, which the simulation does not know in advance, so Optimal is
only offered in the standalone page-replacement visualizer.
"""

ONLINE_POLICIES = ["FIFO", "LRU"]


class PagedMemory:
    def __init__(self, num_frames, policy="FIFO"):
        if num_frames <= 0:
            raise ValueError("Number of frames must be greater than 0.")
        if policy not in ONLINE_POLICIES:
            raise ValueError("The integrated simulation supports FIFO or LRU replacement.")
        self.policy = policy
        # each frame: None or {"pid", "page", "loaded_at", "last_used"}
        self.frames = [None] * num_frames
        self.page_tables = {}  # pid -> {page: frame}
        self.num_pages = {}    # pid -> size of its virtual address space
        self.hits = 0
        self.faults = 0

    def add_process(self, pid, num_pages):
        self.page_tables[pid] = {}
        self.num_pages[pid] = num_pages

    def is_resident(self, pid, page):
        return page in self.page_tables[pid]

    def access(self, pid, page, tick):
        """Return True on a hit, False on a page fault."""
        if not 0 <= page < self.num_pages[pid]:
            raise ValueError(f"{pid}: page {page} is outside its address space.")
        frame = self.page_tables[pid].get(page)
        if frame is None:
            self.faults += 1
            return False
        self.frames[frame]["last_used"] = tick
        self.hits += 1
        return True

    def _victim(self):
        if self.policy == "FIFO":
            return min(range(len(self.frames)), key=lambda f: self.frames[f]["loaded_at"])
        return min(range(len(self.frames)), key=lambda f: self.frames[f]["last_used"])

    def load(self, pid, page, tick):
        """Bring (pid, page) into memory. Returns (frame, evicted) where evicted is
        (victim pid, victim page) or None if a free frame was used."""
        if self.is_resident(pid, page):  # already loaded (should not normally happen)
            return self.page_tables[pid][page], None
        evicted = None
        if None in self.frames:
            frame = self.frames.index(None)
        else:
            frame = self._victim()
            old = self.frames[frame]
            del self.page_tables[old["pid"]][old["page"]]  # the victim's page is no longer resident
            evicted = (old["pid"], old["page"])
        self.frames[frame] = {"pid": pid, "page": page, "loaded_at": tick, "last_used": tick}
        self.page_tables[pid][page] = frame
        return frame, evicted

    def free_process(self, pid):
        """Release every frame owned by pid (when it terminates). Returns the frame numbers."""
        freed = []
        for f, content in enumerate(self.frames):
            if content is not None and content["pid"] == pid:
                self.frames[f] = None
                freed.append(f)
        self.page_tables[pid] = {}
        return freed

    def used_frames(self):
        return sum(1 for f in self.frames if f is not None)

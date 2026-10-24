"""A small virtual file system kept entirely in memory.

Nothing here touches the real disk of the host computer.

Model:
    * A tree of directories and files, addressed by absolute paths like "/docs/a.txt".
    * The simulated disk has `total_blocks` blocks of `block_size` characters.
    * A file of length L uses ceil(L / block_size) blocks (an empty file uses 0).
    * Blocks are allocated individually (indexed allocation): a file gets the
      lowest-numbered free blocks, which need not be next to each other.
      Growing a file adds blocks; shrinking or deleting it frees them.
    * If a write needs more blocks than are free, it fails and nothing changes.
"""

import math


class FileSystemError(ValueError):
    """Raised for invalid paths, missing files, duplicate names, a full disk, etc."""


class File:
    def __init__(self, name, content=""):
        self.name = name
        self.content = content
        self.blocks = []


class Directory:
    def __init__(self, name):
        self.name = name
        self.children = {}  # name -> File or Directory


class VirtualFileSystem:
    def __init__(self, total_blocks=64, block_size=16):
        if total_blocks <= 0 or block_size <= 0:
            raise FileSystemError("Disk must have a positive number of blocks and block size.")
        self.total_blocks = total_blocks
        self.block_size = block_size
        self.root = Directory("")
        self.free_blocks = set(range(total_blocks))

    # ------------------------------------------------------------ path helpers

    @staticmethod
    def _parts(path):
        """'/a/b' -> ['a', 'b'];  '/' -> []."""
        if not isinstance(path, str) or not path.startswith("/"):
            raise FileSystemError(f"Path must be absolute (start with '/'): {path!r}")
        stripped = path.strip("/")
        parts = stripped.split("/") if stripped else []
        for p in parts:
            VirtualFileSystem._check_name(p)
        return parts

    @staticmethod
    def _check_name(name):
        if not name or name in (".", "..") or "/" in name:
            raise FileSystemError(f"Invalid name: {name!r}")

    def _node(self, path):
        node = self.root
        for part in self._parts(path):
            if not isinstance(node, Directory) or part not in node.children:
                raise FileSystemError(f"No such file or directory: {path}")
            node = node.children[part]
        return node

    def _parent(self, path):
        """Return (parent directory, final name) for a path that is not the root."""
        parts = self._parts(path)
        if not parts:
            raise FileSystemError("This operation is not allowed on the root directory.")
        parent = self._node("/" + "/".join(parts[:-1]))
        if not isinstance(parent, Directory):
            raise FileSystemError(f"Not a directory: /{'/'.join(parts[:-1])}")
        return parent, parts[-1]

    def _file(self, path):
        node = self._node(path)
        if not isinstance(node, File):
            raise FileSystemError(f"Not a file: {path}")
        return node

    # ------------------------------------------------------------ block allocation

    def blocks_needed(self, length):
        return math.ceil(length / self.block_size)

    def _resize(self, file, new_content):
        """Give `file` exactly enough blocks for `new_content`, or raise without changing anything."""
        needed = self.blocks_needed(len(new_content))
        extra = needed - len(file.blocks)
        if extra > len(self.free_blocks):
            raise FileSystemError(
                f"Disk full: needs {extra} more block(s), only {len(self.free_blocks)} free.")
        if extra > 0:
            new_blocks = sorted(self.free_blocks)[:extra]
            self.free_blocks.difference_update(new_blocks)
            file.blocks.extend(new_blocks)
        elif extra < 0:
            released = file.blocks[needed:]  # shrink from the end of the file
            file.blocks = file.blocks[:needed]
            self.free_blocks.update(released)
        file.content = new_content

    # ------------------------------------------------------------ operations

    def mkdir(self, path):
        parent, name = self._parent(path)
        if name in parent.children:
            raise FileSystemError(f"Already exists: {path}")
        parent.children[name] = Directory(name)

    def create_file(self, path, content=""):
        parent, name = self._parent(path)
        if name in parent.children:
            raise FileSystemError(f"Already exists: {path}")
        file = File(name)
        self._resize(file, content)  # raises before the file is added if the disk is full
        parent.children[name] = file

    def write_file(self, path, content, append=False):
        file = self._file(path)
        self._resize(file, file.content + content if append else content)

    def read_file(self, path):
        return self._file(path).content

    def rename(self, path, new_name):
        self._check_name(new_name)
        parent, name = self._parent(path)
        if name not in parent.children:
            raise FileSystemError(f"No such file or directory: {path}")
        if new_name in parent.children:
            raise FileSystemError(f"Already exists: {new_name}")
        node = parent.children.pop(name)
        node.name = new_name
        parent.children[new_name] = node

    def delete(self, path):
        """Delete a file (freeing its blocks) or an EMPTY directory."""
        parent, name = self._parent(path)
        if name not in parent.children:
            raise FileSystemError(f"No such file or directory: {path}")
        node = parent.children[name]
        if isinstance(node, Directory) and node.children:
            raise FileSystemError(f"Directory not empty: {path}")
        if isinstance(node, File):
            self.free_blocks.update(node.blocks)
        del parent.children[name]

    def list_dir(self, path="/"):
        node = self._node(path)
        if not isinstance(node, Directory):
            raise FileSystemError(f"Not a directory: {path}")
        return [self._entry(child) for _, child in sorted(node.children.items())]

    def stat(self, path):
        return self._entry(self._node(path))

    def exists(self, path):
        try:
            self._node(path)
            return True
        except FileSystemError:
            return False

    def is_file(self, path):
        return self.exists(path) and isinstance(self._node(path), File)

    def file_blocks(self, path):
        return list(self._file(path).blocks)

    def check_write(self, path, content, append=True):
        """Raise FileSystemError if writing `content` to `path` would fail. Changes nothing.

        A missing file is fine as long as its directory exists (the write creates it).
        """
        if self.is_file(path):
            old = self._file(path)
            new_length = len(old.content) + len(content) if append else len(content)
            extra = self.blocks_needed(new_length) - len(old.blocks)
        else:
            parent, name = self._parent(path)  # raises if the directory is missing
            if name in parent.children:
                raise FileSystemError(f"Not a file: {path}")
            extra = self.blocks_needed(len(content))
        if extra > len(self.free_blocks):
            raise FileSystemError(
                f"Disk full: needs {extra} more block(s), only {len(self.free_blocks)} free.")

    def _entry(self, node):
        if isinstance(node, File):
            return {"name": node.name, "type": "file", "size": len(node.content),
                    "blocks": list(node.blocks)}
        return {"name": node.name or "/", "type": "dir", "size": None, "blocks": []}

    def tree(self):
        """Every path in the file system, depth first: [{path, name, type, size, blocks}, ...]."""
        rows = []

        def walk(directory, prefix):
            for name, child in sorted(directory.children.items()):
                path = f"{prefix}/{name}"
                entry = self._entry(child)
                entry["path"] = path
                rows.append(entry)
                if isinstance(child, Directory):
                    walk(child, path)

        walk(self.root, "")
        return rows

    def block_map(self):
        """List of length total_blocks: the owning file path for each block, or None if free."""
        owners = [None] * self.total_blocks
        for entry in self.tree():
            for b in entry["blocks"]:
                owners[b] = entry["path"]
        return owners

    def used_block_count(self):
        return self.total_blocks - len(self.free_blocks)

"""Tests for the virtual file system (in memory only)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from filesystem.vfs import FileSystemError, VirtualFileSystem


def make_fs():
    # 8 blocks of 4 characters each
    return VirtualFileSystem(total_blocks=8, block_size=4)


def test_create_directories_and_list():
    fs = make_fs()
    fs.mkdir("/docs")
    fs.mkdir("/docs/notes")
    fs.create_file("/docs/a.txt", "hi")

    names = [(e["name"], e["type"]) for e in fs.list_dir("/docs")]
    assert names == [("a.txt", "file"), ("notes", "dir")]
    assert fs.list_dir("/") == [{"name": "docs", "type": "dir", "size": None, "blocks": []}]


def test_file_uses_ceiling_of_size_over_block_size():
    fs = make_fs()
    fs.create_file("/a", "")          # 0 blocks
    fs.create_file("/b", "abcd")      # exactly 1 block
    fs.create_file("/c", "abcde")     # 5 chars -> 2 blocks

    assert fs.file_blocks("/a") == []
    assert fs.file_blocks("/b") == [0]
    assert fs.file_blocks("/c") == [1, 2]
    assert fs.used_block_count() == 3


def test_read_and_overwrite():
    fs = make_fs()
    fs.create_file("/a", "hello")
    fs.write_file("/a", "bye")

    assert fs.read_file("/a") == "bye"
    assert fs.file_blocks("/a") == [0]  # shrank from 2 blocks to 1


def test_append_grows_file_and_allocates_blocks():
    fs = make_fs()
    fs.create_file("/a", "abc")
    fs.create_file("/b", "x")         # takes block 1
    fs.write_file("/a", "defgh", append=True)  # 8 chars -> needs 2 blocks

    assert fs.read_file("/a") == "abcdefgh"
    assert fs.file_blocks("/a") == [0, 2]  # blocks need not be contiguous


def test_delete_file_frees_blocks_for_reuse():
    fs = make_fs()
    fs.create_file("/a", "12345678")  # blocks 0, 1
    fs.create_file("/b", "x")         # block 2
    fs.delete("/a")

    assert sorted(fs.free_blocks) == [0, 1, 3, 4, 5, 6, 7]
    fs.create_file("/c", "y")
    assert fs.file_blocks("/c") == [0]
    assert fs.block_map()[:3] == ["/c", None, "/b"]


def test_rename_keeps_content_and_blocks():
    fs = make_fs()
    fs.mkdir("/d")
    fs.create_file("/d/old.txt", "data")
    fs.rename("/d/old.txt", "new.txt")

    assert not fs.exists("/d/old.txt")
    assert fs.read_file("/d/new.txt") == "data"
    assert fs.block_map()[0] == "/d/new.txt"


def test_rename_directory():
    fs = make_fs()
    fs.mkdir("/a")
    fs.create_file("/a/f", "1")
    fs.rename("/a", "b")

    assert fs.read_file("/b/f") == "1"


def test_disk_full_write_fails_without_changes():
    fs = make_fs()
    fs.create_file("/big", "x" * 28)  # 7 of 8 blocks
    with pytest.raises(FileSystemError, match="Disk full"):
        fs.create_file("/more", "x" * 5)  # needs 2
    with pytest.raises(FileSystemError, match="Disk full"):
        fs.write_file("/big", "y" * 8, append=True)

    assert not fs.exists("/more")
    assert len(fs.read_file("/big")) == 28
    assert fs.used_block_count() == 7


def test_check_write():
    fs = make_fs()
    fs.mkdir("/d")
    fs.check_write("/d/new.txt", "abc")       # new file in an existing directory: fine
    with pytest.raises(FileSystemError):
        fs.check_write("/missing/x", "abc")   # directory does not exist
    with pytest.raises(FileSystemError):
        fs.check_write("/d", "abc")           # a directory is not a file
    fs.create_file("/d/f", "")
    with pytest.raises(FileSystemError, match="Disk full"):
        fs.check_write("/d/f", "x" * 40)


@pytest.mark.parametrize("operation", [
    lambda fs: fs.read_file("/missing"),
    lambda fs: fs.create_file("/nodir/a", "x"),
    lambda fs: fs.mkdir("/a/b/c"),
    lambda fs: fs.delete("/missing"),
    lambda fs: fs.rename("/missing", "x"),
    lambda fs: fs.list_dir("/missing"),
])
def test_missing_paths_raise(operation):
    with pytest.raises(FileSystemError):
        operation(make_fs())


def test_duplicate_names_rejected():
    fs = make_fs()
    fs.mkdir("/d")
    fs.create_file("/f", "")
    with pytest.raises(FileSystemError, match="Already exists"):
        fs.mkdir("/d")
    with pytest.raises(FileSystemError, match="Already exists"):
        fs.create_file("/f", "")
    with pytest.raises(FileSystemError, match="Already exists"):
        fs.rename("/f", "d")


def test_invalid_operations():
    fs = make_fs()
    fs.mkdir("/d")
    fs.create_file("/d/f", "")
    with pytest.raises(FileSystemError, match="not empty"):
        fs.delete("/d")
    with pytest.raises(FileSystemError, match="root"):
        fs.delete("/")
    with pytest.raises(FileSystemError, match="Not a file"):
        fs.read_file("/d")
    with pytest.raises(FileSystemError, match="Not a directory"):
        fs.list_dir("/d/f")
    with pytest.raises(FileSystemError, match="Not a directory"):
        fs.create_file("/d/f/x", "")


@pytest.mark.parametrize("path", ["relative.txt", "/a/../b", "/./x", ""])
def test_invalid_paths(path):
    with pytest.raises(FileSystemError):
        make_fs().create_file(path, "")


def test_empty_directory_can_be_deleted():
    fs = make_fs()
    fs.mkdir("/d")
    fs.delete("/d")

    assert fs.list_dir("/") == []


def test_tree_lists_every_path():
    fs = make_fs()
    fs.mkdir("/a")
    fs.create_file("/a/x", "12")
    fs.create_file("/z", "")

    assert [(e["path"], e["type"], e["size"]) for e in fs.tree()] == [
        ("/a", "dir", None), ("/a/x", "file", 2), ("/z", "file", 0),
    ]

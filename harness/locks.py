"""Cross-process category locks for case mutations, runs, and archive moves."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from harness.config import CATEGORIES, ROOT


@contextmanager
def category_lock(category: str, root: Path = ROOT, *, exclusive: bool = False):
    """Hold a shared run lock or a nonblocking exclusive archive lock."""
    if category not in CATEGORIES:
        raise ValueError("unknown category")
    categories = root / "categories"
    directory = categories / category
    if categories.is_symlink() or directory.is_symlink():
        raise ValueError("category path must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".harness.lock"
    if path.is_symlink():
        raise ValueError("category lock must not be a symlink")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        mode = fcntl.LOCK_EX | fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, mode)
        except BlockingIOError as exc:
            raise ValueError(f"category {category} is active; archive or restore refused") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

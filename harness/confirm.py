"""Shared confirmation for ordinary local operations only.

This is not an authentication, security approval, or owner verdict mechanism.
"""

from __future__ import annotations

import sys
from typing import Callable


class ConfirmationUnavailable(ValueError):
    """An interactive confirmation cannot be obtained from this input."""


class ConfirmationCancelled(Exception):
    """EOF or Ctrl+C ended the confirmation without accepting it."""


def ask(prompt: str, *, yes: bool = False, input_fn: Callable[[str], str] | None = None,
        tty: bool | None = None) -> bool:
    """Ask Y/n; blank accepts only at a live prompt. --yes bypasses this call."""
    if yes:
        return True
    if tty is None:
        tty = sys.stdin.isatty()
    if not tty:
        raise ConfirmationUnavailable("confirmation needs a TTY; use --yes with a complete explicit action")
    read = input_fn or input
    while True:
        try:
            answer = read(f"{prompt} [Y/n]: ").strip().casefold()
        except (EOFError, KeyboardInterrupt) as exc:
            raise ConfirmationCancelled from exc
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Enter y or n.", flush=True)

"""Extract a hash-verified official Ghidra ZIP, preserving executable modes.

The caller must verify the published SHA-256 before invoking this helper.
"""
from pathlib import Path
from zipfile import ZipFile
import sys

archive = Path(sys.argv[1])
destination = Path(sys.argv[2]).resolve()
destination.mkdir(parents=True, exist_ok=False)
with ZipFile(archive) as source:
    for member in source.infolist():
        relative = Path(member.filename)
        if relative.is_absolute() or any(part in (".", "..") for part in relative.parts):
            raise ValueError("unsafe archive member")
        target = destination / relative
        if not target.resolve().is_relative_to(destination):
            raise ValueError("archive member escapes destination")
        mode = member.external_attr >> 16
        if (mode & 0o170000) == 0o120000:
            raise ValueError("symlinks are not accepted in Ghidra archive")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ValueError("duplicate archive member")
        with source.open(member) as input_file, target.open("xb") as output:
            while chunk := input_file.read(1 << 20):
                output.write(chunk)
        if mode & 0o111:
            target.chmod(target.stat().st_mode | (mode & 0o111))
print("Extracted verified Ghidra archive with native executable modes")

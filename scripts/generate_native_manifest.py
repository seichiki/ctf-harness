"""Record exact Ubuntu package versions and SHA-256 for local native tools."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / ".local/tools/ubuntu-debs"
OUTPUT = ROOT / "docs/NATIVE-APT-MANIFEST.md"


def main() -> int:
    debs = sorted(ARCHIVE.glob("*.deb"))
    if not debs:
        raise SystemExit("No clone-local Ubuntu packages found; run ./scripts/setup-native-tools.sh")
    rows = []
    for deb in debs:
        fields = subprocess.check_output(
            ["dpkg-deb", "-f", str(deb), "Package", "Version", "Architecture"],
            text=True, timeout=5,
        )
        meta = dict(line.split(": ", 1) for line in fields.splitlines() if ": " in line)
        digest = hashlib.sha256(deb.read_bytes()).hexdigest()
        rows.append(f"| `{meta['Package']}` | `{meta['Version']}` | `{meta['Architecture']}` | `{digest}` |")
    OUTPUT.write_text(
        "# Native Ubuntu package snapshot / Ubuntu パッケージ記録\n\n"
        "Snapshot from `./scripts/setup-native-tools.sh` on Ubuntu 26.04 x86-64. "
        "Packages came from the host's configured official Ubuntu apt repositories and were "
        "extracted under ignored `.local/tools/ubuntu-root/` without sudo. "
        "This records observed package files; the setup script resolves current supported "
        "versions from the host repository. Package contents stay in the clone, not Git.\n\n"
        "| Package | Version | Architecture | Downloaded .deb SHA-256 |\n"
        "| --- | --- | --- | --- |\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT} with {len(rows)} package records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

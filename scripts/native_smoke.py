"""Offline, harmless smoke checks for the project-local native tools."""
from __future__ import annotations

import os
import select
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image
from scapy.all import Ether, IP, UDP, Raw, wrpcap

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / ".local/tools/bin"


def run(name: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": str(BIN) + os.pathsep + os.environ.get("PATH", "")}
    result = subprocess.run([str(BIN / name), *args], cwd=cwd, env=env,
                            text=True, capture_output=True, timeout=30, check=False)
    print(f"{name}: exit={result.returncode}")
    if result.returncode:
        print((result.stderr or result.stdout)[:500])
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ctf-native-smoke-") as folder:
        root = Path(folder)
        source = root / "sample.c"
        source.write_text("int helper(int x){return x*7+3;} int main(void){return helper(2);}\n")
        binary = root / "sample"
        subprocess.run(["cc", "-g", "-o", str(binary), str(source)], check=True)
        gdb = run("gdb", "--batch", "-q", "-ex", "break main", "-ex", "run",
                  "-ex", "info registers rip", str(binary))
        if gdb.returncode == 0 and "rip" in gdb.stdout:
            print("gdb: live breakpoint/register inspection OK")
        else:
            print("gdb: live ptrace may be denied by the execution sandbox")

        image = root / "sample.png"
        Image.new("RGB", (2, 2), "red").save(image)
        exif = run("exiftool", "-s3", "-FileType", str(image))
        assert exif.returncode == 0 and exif.stdout.strip() == "PNG"

        packet = root / "sample.pcap"
        wrpcap(str(packet), [Ether(src="02:00:00:00:00:10", dst="02:00:00:00:00:20")/
                              IP(src="192.0.2.10", dst="192.0.2.20")/
                              UDP(sport=12345, dport=4242)/Raw(b"fixture")])
        tshark = run("tshark", "-r", str(packet), "-T", "fields", "-e", "ip.src",
                     "-e", "udp.dstport")
        assert tshark.returncode == 0 and "192.0.2.10" in tshark.stdout and "4242" in tshark.stdout

        embedded = root / "sample.bin"
        archive = root / "payload.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("proof.txt", "offline fixture\n")
        embedded.write_bytes(b"harmless-prefix:" + archive.read_bytes())
        scan = run("binwalk", str(embedded), cwd=root)
        assert scan.returncode == 0 and "zip" in scan.stdout.lower()
        extracted = root / "extracted"
        extraction = run("binwalk", "-e", "-C", str(extracted), str(embedded), cwd=root)
        assert extraction.returncode == 0
        found = list(extracted.rglob("proof.txt"))
        print(f"binwalk: ZIP signature found; extracted proof files={len(found)}")
        if not found:
            print("binwalk extraction output:", extraction.stdout[:800], extraction.stderr[:800])
            print("binwalk extraction paths:", [str(p.relative_to(root)) for p in extracted.rglob("*")][:20])
        assert found and found[0].read_text() == "offline fixture\n"

        if (BIN / "steghide").is_file():
            cover = root / "stego-cover.bmp"
            Image.new("RGB", (128, 128), "blue").save(cover)
            payload = root / "stego-payload.txt"
            payload.write_text("offline steghide fixture\n", encoding="utf-8")
            stego = root / "stego-output.bmp"
            embedded = run("steghide", "embed", "-cf", str(cover), "-ef", str(payload),
                           "-sf", str(stego), "-p", "fixture-pass", "-f", cwd=root)
            assert embedded.returncode == 0 and stego.is_file()
            recovered = root / "stego-recovered.txt"
            extracted = run("steghide", "extract", "-sf", str(stego), "-xf", str(recovered),
                            "-p", "fixture-pass", "-f", cwd=root)
            assert extracted.returncode == 0 and recovered.read_bytes() == payload.read_bytes()
            print("steghide: local BMP embed/extract round trip OK")
        else:
            print("steghide: not installed; local round-trip smoke skipped")

        left, right = root / "pty-left", root / "pty-right"
        bridge = subprocess.Popen([str(BIN / "socat"), f"PTY,link={left},raw,echo=0",
                                   f"PTY,link={right},raw,echo=0"],
                                  cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not (left.is_symlink() and right.is_symlink()):
                if time.monotonic() >= deadline or bridge.poll() is not None:
                    raise AssertionError("socat did not create local PTYs")
                time.sleep(0.05)
            left_fd = os.open(left, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            right_fd = os.open(right, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                os.write(left_fd, b"local-fixture")
                ready, _, _ = select.select([right_fd], [], [], 3)
                assert ready and os.read(right_fd, 64) == b"local-fixture"
            finally:
                os.close(left_fd)
                os.close(right_fd)
            print("socat: local PTY-to-PTY byte relay OK")
        finally:
            bridge.terminate()
            bridge.communicate(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

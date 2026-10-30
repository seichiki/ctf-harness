"""Install only named, curated case tools under the clone's ignored .local tree."""

from __future__ import annotations

import os
import hashlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from harness.config import ROOT
from harness.ondemand import SPECS

TOOLS = ROOT / ".local/tools"
BIN = TOOLS / "bin"
SYSROOT = TOOLS / "ubuntu-root"
APT = {"tsk": "sleuthkit", "foremost": "foremost", "scalpel": "scalpel",
       "qpdf": "qpdf", "sqlmap": "sqlmap", "ffuf": "ffuf", "hashcat": "hashcat",
       "dirsearch": "dirsearch", "gobuster": "gobuster"}
BASIC_APT = {"debugfs": "e2fsprogs", "curl": "curl", "jq": "jq", "openssl": "openssl",
             "readelf": "binutils", "objdump": "binutils", "strings": "binutils",
             "file": "file"}
UV = {"volatility3": "volatility3", "xortool": "xortool", "peepdf-3": "peepdf-3",
      "flask-unsign": "flask-unsign"}
SOURCE = {"xsstrike": ("https://github.com/s0md3v/XSStrike.git", "xsstrike.py"),
          "jwt_tool": ("https://github.com/ticarpi/jwt_tool.git", "jwt_tool.py"),
          "ssrfmap": ("https://github.com/swisskyrepo/SSRFmap.git", "ssrfmap.py")}


def _run(*command: str, cwd: Path = ROOT, env: dict | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _wrapper(name: str, command: str) -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    path = BIN / name
    path.write_text("#!/bin/sh\nset -eu\n" + command + "\n", encoding="utf-8")
    path.chmod(0o755)


def _apt(name: str) -> None:
    package = (APT | BASIC_APT)[name]
    print(f"Source: configured Ubuntu package repository; package {package}", flush=True)
    result = subprocess.run(["apt-get", "-s", "install", "--no-install-recommends", package],
                            capture_output=True, text=True, check=True)
    packages = set(re.findall(r"^Inst (\S+)", result.stdout, re.MULTILINE))
    packages.add(package)
    archives = TOOLS / "ubuntu-debs"
    archives.mkdir(parents=True, exist_ok=True)
    for dependency in sorted(packages):
        _run("apt-get", "download", dependency, cwd=archives)
        files = sorted(archives.glob(dependency.replace(":amd64", "") + "_*.deb"))
        if not files:
            raise RuntimeError(f"downloaded archive missing for {dependency}")
        _run("dpkg-deb", "-x", str(files[-1]), str(SYSROOT))
    executables = ("fls", "mmls", "icat", "fsstat", "istat") if name == "tsk" else (SPECS[name][1] if name in SPECS else name,)
    for executable in executables:
        relative = f"usr/bin/{executable}" if (SYSROOT / "usr/bin" / executable).is_file() else f"usr/sbin/{executable}"
        if not (SYSROOT / relative).is_file():
            raise RuntimeError(f"Ubuntu package did not contain {executable}")
        _wrapper(executable,
                 f'root={shlex_quote(str(TOOLS))}\n'
                 'export LD_LIBRARY_PATH="$root/ubuntu-root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                 'export PYTHONPATH="$root/ubuntu-root/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"\n'
                 'export PATH="$root/ubuntu-root/usr/bin:$PATH"\n'
                 f'exec "$root/ubuntu-root/{relative}" "$@"')


def shlex_quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


def _uv(name: str) -> None:
    print(f"Source: PyPI via uv; distribution {UV[name]}", flush=True)
    env = dict(os.environ, UV_TOOL_DIR=str(TOOLS / "uv-tools"), UV_TOOL_BIN_DIR=str(BIN),
               UV_CACHE_DIR=str(TOOLS / "uv-cache"))
    BIN.mkdir(parents=True, exist_ok=True)
    _run("uv", "tool", "install", "--python", "3.12", UV[name], env=env)
    if not (BIN / SPECS[name][1]).is_file():
        raise RuntimeError(f"uv did not provide {SPECS[name][1]}")


def _source(name: str) -> None:
    url, script = SOURCE[name]
    print(f"Source: {url}", flush=True)
    checkout = TOOLS / "source" / name
    checkout.parent.mkdir(parents=True, exist_ok=True)
    if not (checkout / ".git").is_dir():
        _run("git", "clone", "--depth", "1", url, str(checkout))
    print("Source revision:", subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip())
    venv = TOOLS / "venvs" / name
    if not (venv / "bin/python").is_file():
        _run("uv", "venv", "--python", "3.12", str(venv))
    requirements = checkout / "requirements.txt"
    if requirements.is_file():
        _run("uv", "pip", "install", "--python", str(venv / "bin/python"), "-r", str(requirements))
    if not (checkout / script).is_file():
        raise RuntimeError(f"source repository did not contain {script}")
    _wrapper(SPECS[name][1], f'exec {shlex_quote(str(venv / "bin/python"))} {shlex_quote(str(checkout / script))} "$@"')


def _java() -> str:
    local = TOOLS / "jdk-21.0.13+9/bin/java"
    if local.is_file():
        return str(local)
    system = shutil.which("java")
    if system:
        return system
    raise RuntimeError("Java is required; install the project-local REA/Ghidra bundle first")


def _ysoserial() -> None:
    jar = TOOLS / "ysoserial/ysoserial-all.jar"
    print("Source: https://github.com/frohoff/ysoserial/releases/download/v0.0.6/ysoserial-all.jar", flush=True)
    jar.parent.mkdir(parents=True, exist_ok=True)
    if not jar.is_file():
        _run("curl", "--fail", "--location", "--silent", "--show-error", "--output", str(jar),
             "https://github.com/frohoff/ysoserial/releases/download/v0.0.6/ysoserial-all.jar")
    print("SHA-256:", hashlib.sha256(jar.read_bytes()).hexdigest(), flush=True)
    _wrapper("ysoserial", f'exec {shlex_quote(_java())} -jar {shlex_quote(str(jar))} "$@"')


def _kaitai() -> None:
    archive = TOOLS / "kaitai/kaitai-struct-compiler-0.11.zip"
    print("Source: https://github.com/kaitai-io/kaitai_struct_compiler/releases/download/0.11/kaitai-struct-compiler-0.11.zip", flush=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        _run("curl", "--fail", "--location", "--silent", "--show-error", "--output", str(archive),
             "https://github.com/kaitai-io/kaitai_struct_compiler/releases/download/0.11/kaitai-struct-compiler-0.11.zip")
    print("SHA-256:", hashlib.sha256(archive.read_bytes()).hexdigest(), flush=True)
    target = archive.parent / "unpacked"
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            destination = (target / entry.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise RuntimeError("unsafe compiler archive path")
        bundle.extractall(target)
    launchers = list(target.rglob("kaitai-struct-compiler"))
    if len(launchers) != 1:
        raise RuntimeError("compiler launcher not found uniquely")
    launchers[0].chmod(0o755)
    java = _java()
    java_home = f'export JAVA_HOME={shlex_quote(str(Path(java).parent.parent))}\n' if java.startswith(str(TOOLS)) else ""
    _wrapper("ksc", java_home + f'exec {shlex_quote(str(launchers[0]))} "$@"')


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=sorted(set(SPECS) | set(BASIC_APT)))
    args = parser.parse_args(argv)
    if args.name in APT or args.name in BASIC_APT:
        _apt(args.name)
    elif args.name in UV:
        _uv(args.name)
    elif args.name in SOURCE:
        _source(args.name)
    elif args.name == "ysoserial":
        _ysoserial()
    elif args.name == "kaitai-struct":
        _kaitai()
    else:
        raise RuntimeError("no curated install recipe")
    print(f"Installed {args.name} under {TOOLS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

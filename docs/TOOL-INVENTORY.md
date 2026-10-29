# Tool inventory / ツール一覧

Snapshot: 2026-10-29, WSL Ubuntu x86-64, isolated clone `~/ctf/ctf-harness-test`.
This is an installed-state snapshot. For a new clone, run `uv sync --locked`, optionally
`./scripts/setup-rea-ghidra.sh`, then `./ctf-start tools --missing-only --json`.
The checker reads status and never installs tools. `uv.lock` and
`scripts/rea-npm/package-lock.json` are the reproducible package records.

## Baseline before this addition / 追加前

The harness declared no Python dependencies; none of the 16 direct packages below imported
in its project `uv run --offline --locked python` environment. WSL PATH already had
`curl`, `jq`, `readelf`, `objdump`, `file`, `strings`, and `nc`.
All seven category skill files were present, but skills are instructions, not installations.

## Explicit category packages / 明示的な追加 (16)

| Category | Distribution | Installed version |
| --- | --- | --- |
| web | `httpx` | `0.28.1` |
| web | `beautifulsoup4` | `4.15.0` |
| web | `lxml` | `6.1.3` |
| crypto | `pycryptodome` | `4.2.0` |
| crypto | `sympy` | `1.14.0` |
| pwn | `pwntools` | `4.15.0` |
| reverse | `z3-solver` | `5.3.2.0` |
| reverse | `capstone` | `5.0.9` |
| reverse | `pyelftools` | `0.33` |
| reverse | `pefile` | `2024.8.26` |
| forensics | `pillow` | `13.0.0` |
| forensics | `scapy` | `2.8.0` |
| forensics | `ExifRead` | `3.5.1` |
| forensics | `pypdf` | `6.21.4` |
| osint | `dnspython` | `2.9.0` |
| misc | `regex` | `2026.9.29` |

## Transitive Python packages / 間接依存 (38)

These were installed by uv for the selected direct packages; they are not separately
requested features. Exact artifacts and hashes are in `uv.lock`.

| Distribution | Installed version |
| --- | --- |
| `anyio` | `4.15.1` |
| `bcrypt` | `5.0.0` |
| `certifi` | `2026.10.23` |
| `cffi` | `2.1.1` |
| `charset-normalizer` | `3.5.2` |
| `colored-traceback` | `0.4.2` |
| `cryptography` | `50.0.2` |
| `h11` | `0.16.0` |
| `httpcore` | `1.0.9` |
| `idna` | `3.20` |
| `intervaltree` | `3.2.1` |
| `invoke` | `3.0.3` |
| `Mako` | `1.4.3` |
| `MarkupSafe` | `3.0.4` |
| `mpmath` | `1.3.0` |
| `packaging` | `26.3` |
| `paramiko` | `5.1.0` |
| `pip` | `26.2.2` |
| `plumbum` | `2.0.2` |
| `psutil` | `7.2.2` |
| `pycparser` | `3.12` |
| `Pygments` | `2.21.0` |
| `PyNaCl` | `1.6.2` |
| `pyserial` | `3.5` |
| `PySocks` | `1.7.1` |
| `python-dateutil` | `3.0.0` |
| `requests` | `2.34.2` |
| `ROPGadget` | `7.7` |
| `rpyc` | `6.0.2` |
| `six` | `1.17.0` |
| `sortedcontainers` | `2.4.0` |
| `soupsieve` | `3.0.4` |
| `typing_extensions` | `4.16.0` |
| `tzdata` | `2026.6` |
| `unicorn` | `2.1.2` |
| `unix-ar` | `0.2.1` |
| `urllib3` | `2.8.0` |
| `zstandard` | `0.25.0` |

## Native tools / 外部ツール

| Tool | Current state | Management |
| --- | --- | --- |
| Ghidra 12.1.4 | installed, local sample decompile passed | ignored `.local/tools/`; optional pinned installer |
| REA 6.8.0 | installed, `rea-static` sample passed | ignored `.local/tools/`; npm lock |
| REA inside Codex network-off child | blocked on this host: local Unix socket `Operation not permitted` | profile-specific |
| REA inside Codex network-on child | self-built ELF `helper` decompile passed once | one approved invocation only; not a general network guarantee |
| Temurin JDK 21.0.13+9 | installed | ignored `.local/tools/`; official SHA-256 verified |
| Node 24.22.1 | installed | ignored `.local/tools/`; official SHA-256 verified |
| curl, jq, readelf, objdump, file, strings, nc | already present on WSL PATH | system; not installed by this task |
| GDB 17.1, socat 1.8.1.1 | installed; breakpoint/register and local PTY relay passed | official Ubuntu packages extracted under ignored `.local/tools/` |
| ExifTool 13.50, TShark 4.6.4 | installed; PNG metadata and offline PCAP decoding passed | official Ubuntu packages extracted locally; no live capture permission changes |
| Binwalk 3.1.0, 7-Zip 26.00 | installed; embedded ZIP detected and extracted | official crates.io locked build and Ubuntu 7-Zip, both local |

The native tools above were absent at baseline and added at the user's request.
`./scripts/setup-native-tools.sh` repeats the clone-local Ubuntu 26.04 x86-64 setup;
`uv run --offline --locked --no-sync python scripts/native_smoke.py` checks harmless
offline fixtures. The checker reports binary launch/version, while the smoke checks
actual selected functions. TShark currently warns that its optional Falco plugin
lacks `libsinsp.so.0`; basic offline PCAP decoding passed. Other Binwalk signatures
may require further external extractors. See [setup and limitations](NATIVE-TOOLS.md).

これらは最初は未導入でしたが、依頼に応じてクローン内に追加しました。別クローンでは
`./scripts/setup-native-tools.sh` を実行し、チェッカーとオフライン試料で確認して
ください。TShark の Falco 用プラグインには未解決の任意ライブラリ警告があります。

The direct `pycryptodome` distribution is **4.2.0**, confirmed both in the locked
distribution metadata and by importing `Crypto.Cipher.AES` and `Crypto.Hash.SHA256`.
PyPI lists 4.2.0 as a genuine release: https://pypi.org/project/pycryptodome/4.2.0/

# Install missing tools

From a fresh clone, install uv and Python 3.12 first. Then run:

```sh
./ctf-start tools --missing-only
./ctf-start tools install
# or: ./ctf-start tools install --all
# or: ./ctf-start tools install --required
```

The no-option installer shows only currently missing, incompatible, or misconfigured tools. Use Up/Down to move, Space to toggle a checkbox, Enter to finish selection, or Esc/Ctrl+C to cancel. `--all` and `--required` bypass selection and are mutually exclusive. All modes print the complete plan and ask `Y/n` before installation; Enter means yes. `-y`/`--yes` skips only that final prompt after showing the plan. Without a TTY, use `--yes` with `--all` or `--required`; `tools install --yes` alone still needs interactive tool selection and cannot silently choose all tools.

One progress unit represents one executable install action, not download bytes. The bar counts finished units, including failures and skips. STARTED/COMPLETED/FAILED/SKIPPED output appears as each unit changes state. The active unit streams sanitized output, with a heartbeat during silent work. A summary and unit logs are saved in ignored `.local/install-runs/<timestamp-id>/`. Recheck with `./ctf-start tools --missing-only` after partial failure. An interrupt stops only the installer-owned subprocess group and keeps already installed files.

The installer starts with `uv run --no-project --offline --python 3.12`, so it does not require the project `.venv`. Python packages are an indivisible `uv sync --locked` unit for all seven default groups; selecting one missing Python package installs the whole locked bundle. The REA/Ghidra bundle uses the pinned official releases and local script. Binwalk includes local 7-Zip for extraction. Native tools use `scripts/setup-native-tools.sh --only <tool>` on Ubuntu 26.04 x86-64. The plan names origins, versions when pinned, dependencies and destinations before confirmation.

There is no project-local installer for the Codex CLI/sign-in or basic OS tools such as curl, jq, OpenSSL, file and binutils. When missing, these appear as manual-only SKIPPED units with guidance; the installer exits nonzero. No sudo, global CA, firewall, proxy, capture privilege, or authentication setting is changed. The native Ubuntu package revisions are selected from the configured distro repository at installation time; the Python versions are fixed in `uv.lock`. A successful command is checked again by the current tool checker, which does not prove usability in every future Codex sandbox.

`--yes` does not enter credentials, accept third-party agreements, or bypass OS, Codex, or administrator permission prompts. An EOF or Ctrl+C at the confirmation prompt cancels the plan.

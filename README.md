[English](README.md) | [日本語](README.ja.md)

# CTF harness

A source-only, category-aware Codex CLI harness. It uses **your own ChatGPT Codex sign-in** and a model ID you choose from your account. Public defaults are Daybreak **off**, **single** session, and sandbox outbound network **off**. Daybreak Blue, external multi-session orchestration, and sandbox network access are opt-in. No API key, paid model API fallback, target submission, challenge input, or past run is included.

## Quick start on Linux or Ubuntu WSL

Prerequisites: Codex CLI 0.164.0 or newer with a ChatGPT sign-in, [uv](https://docs.astral.sh/uv/) and Python 3.12. Codex and uv installation are personal prerequisites; this repository does not install them or change global settings. `./ctf-start doctor` reports missing CLI, uv, lockfile, and bundled skills. Model availability and reasoning effort depend on your account and are checked by Codex on an actual run, without automatic fallback.

```sh
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
uv sync --locked                 # creates the local environment; may fetch Python 3.12 if missing
codex login                      # sign in with your own ChatGPT account
./ctf-start doctor
./ctf-start setup --model <MODEL_ID_FROM_YOUR_ACCOUNT>
./ctf-start                     # new-problem wizard in a terminal
```

The no-argument wizard starts a new problem directly. Choose a category and name; the case ID and draft directory are created immediately. It displays `配布ファイル保存先：<case>/input/files` and `Enterで完了`. Put distributed files there yourself, if any, and press Enter. The wizard lists the files found. Enter the multiline problem statement and end with `/end`. Choose local input or one authorized live endpoint, a positive whole-minute limit (default 15), and test or production. Review settings and type `RUN` to seal and start. For a live target with saved network off, `ENABLE` is required for that run only. `/cancel`, EOF, or Ctrl-C before `RUN` leaves a named draft with no model or target request. Use a real terminal; noninteractive callers should use explicit commands. At the end, it prints `引継ぎファイル：...` if created, then `ログ保存先：...`.

Existing case reruns and archive/restore remain explicit commands. For automation or manual preparation:

```sh
./ctf-start list
./ctf-start init --category crypto --case-id sample --scope-note 'My authorized local CTF problem'
# Put statement and supplied files into categories/crypto/cases/sample/input/
./ctf-start seal --category crypto --case-id sample
./ctf-start run --category crypto --case-id sample --preset test --dry-run
./ctf-start run --category crypto --case-id sample --preset test
```

`setup` writes only `.local/config.toml`, which Git ignores. It stores the model ID, effort, Daybreak, orchestration, network access, live progress, and optional HTTP proxy endpoint; it does **not** copy authentication. Existing local configs without new fields use safe defaults (`network_access = "off"`, `progress = false`, `proxy_url = ""`). If you already have a local config, edit it directly after reviewing `config.example.toml`; `setup` will not overwrite it. A model name in this file does not grant access. `run` reads saved values, then applies explicit CLI overrides only to that invocation: `--model`, `--effort`, `--daybreak`, `--orchestration`, `--network-access off|on`, `--progress`/`--no-progress`, and `--proxy URL`/`--no-proxy`.

After setting your personal defaults, use `./ctf-start` to create a new problem interactively. For an existing sealed case, `./ctf-start run --category web --case-id <existing-case-id> --preset test` starts a fresh run. A one-off quiet explicit run can use `--quiet` to suppress startup status and live progress while retaining the final JSON on stdout. For other explicit runs, a short requested-settings line goes to stderr; it says only whether a proxy is active, never its URL. Check the dry-run plan before real target access.

Owner example, kept private in `.local/config.toml`: `./ctf-start setup --model gpt-5.6-sol --effort high --daybreak blue --orchestration multi`. This is optional; a friend without Blue can keep `--daybreak off` and use their own available model. If the selected model/effort/program fails, the run records the error and stops; it never chooses a different one silently.

External runs create `HANDOFF.md` early in each run directory and update it at role and tool checkpoints even when terminal progress is off. It groups the recorded case scope, requested settings, sanitized commands and exit states, role candidates or unavailable reports, and relative evidence paths. It does not prove target acceptance. Authentication masking is best effort, while parsed CTF candidates are shown as reported; review before sharing. Input binaries and full logs are referenced rather than embedded, so copy them separately for a portable handoff. A hard kill or power loss may leave only the last completed checkpoint.
Interactive sessions create a basic handoff with settings and exit status; terminal actions inside the interactive Codex UI are not captured by this harness.

During a new-problem wizard run, a candidate from a completed valid role report is shown with a stable ID such as `C1`. Submit it yourself to the official challenge. If that **exact candidate** is accepted while the run is still active, type `solved` in the same terminal, select its ID, inspect the full string, then type `ACCEPT C1`. Only terminal input can do this; model messages and tool output cannot. The harness saves `OWNER_CONFIRMATION.json` and attempts `SOLUTION.md` before stopping remaining run-owned Codex process groups and records `user_confirmed` in `result.json`. This means **owner-reported official acceptance**, not server verification by the harness. `SOLUTION.md` combines recorded command starts/exits with clearly labeled role-reported method, evidence, reproduction commands and limitations; missing outputs and steps are not invented. Keep the original input and event files with it for a complete writeup. To enable the same control on an explicit existing-case run, add `--owner-confirmation` in a terminal; it is off by default and cannot be combined with `--quiet` or interactive orchestration. Ctrl-C still cancels an unconfirmed run.
The harness atomically saves `OWNER_CONFIRMATION.json` before stopping child processes. If `SOLUTION.md` cannot be generated, the acceptance record and original role logs remain, and finalization retries the writeup. If even the acceptance record cannot be saved, the run is not stopped or marked confirmed. The control requires the foreground terminal; its input is not passed to child Codex processes.

## Modes and controls

`--orchestration single` makes one fresh CLI session and is the public default. `--orchestration multi` runs an initial verifier, two independent solver sessions in parallel, and a separate frozen-report review. The sessions are separate CLI processes, not native subagents. `--orchestration interactive` opens one fresh terminal session without submitting a challenge prompt. For interactive Blue, the documented `daybreak=true` setting is requested; select the visible **Daybreak Blue** item in `/model` before typing the challenge. This manual selection is recorded as user-confirmed or unknown, never as verified server application. Off mode explicitly sets `daybreak=false` and a non-Blue model. Noninteractive off additionally requests `--cyber-access-program standard`; Blue mode requests `daybreak_blue` on each `codex exec`. Global user config is ignored for noninteractive runs, while the existing ChatGPT login is retained. API-key environment variables are removed from child Codex processes.

`--preset test` defaults to similar-search off and answer reference off. `--preset production` defaults to similar-search on and answer reference off. Use `--similar-search on|off` independently of the preset. Use `--answer-reference on --answer-file /path/to/reference` only when you intend that file to be available to every role. Each change creates a fresh run folder. Search on uses built-in Codex web search and the local `ctf-similar-search` adapter; no Tavily key or additional API is needed. Search off sets `web_search=disabled` and omits that adapter from the role directory. Search and answer-reference switches do not change sandbox outbound network access. Runs and cases are ignored by Git, but directory separation does not prevent OS-level reads of other accessible files.

Sandbox outbound network access defaults to off for every preset. For one authorized live case, use `./ctf-start run --category web --case-id <fresh-case-id> --preset test --network-access on --dry-run`, then repeat without `--dry-run` after checking the plan. This requests `sandbox_workspace_write.network_access=true` for each role; off explicitly requests `false`. **On is not limited to the case host**: the target in the case manifest is an instruction, not a network firewall. Dry-run, `settings.json`, and `result.json` record the requested choice; they do not prove effective network enforcement. The harness requests `approval_policy=on-request`, but Codex CLI 0.164.0 has been observed displaying `approval: never` for a noninteractive `codex exec`; do not rely on an approval prompt during external runs. The workspace-write sandbox remains selected, and failures do not trigger a less restrictive fallback.

Each case has a positive whole-minute shared deadline for external runs. The default is 15 minutes and there is no fixed maximum; all multi roles share it. The launcher records prompts, CLI flags, JSONL events, usage when supplied, source URLs, and a candidate hash. `candidate_pending` means **you** still need to verify the candidate. Unknown challenge binaries/scripts must not run on the host; use a separately approved isolation environment. There is no automatic flag submission.

For live terminal status during an external run, set `progress = true` in your private config or add `--progress` for one run. `--no-progress` temporarily disables a saved `true` value. Progress prints timestamped role starts/finishes and command/tool starts/results to **stderr** while the final JSON stays on stdout. Command starts show the actual shell command, including ordinary arguments and URLs; event IDs link starts to completions and exit codes. After each role's report is parsed, the display shows its exact candidate labeled unverified with a reported basis, a valid empty candidate, or that no valid report was available. It never automatically dumps command output, agent messages, or hidden reasoning. Control sequences are removed; common credentials, authorization headers, cookies, and sensitive query values are masked. **Masking is best effort, not a guarantee**; use progress only in a private terminal. Commands over 420 displayed characters are explicitly marked truncated. Candidate flags are shown as reported, without credential masking. Complete JSONL event files remain in each role's run directory and can contain secrets. Codex may delay writing an event, so this is a live event feed rather than a guarantee of continuous updates. A hard process kill or power loss cannot produce a final status line.

`proxy_url` is optional and defaults to empty; Caido is never needed for ordinary runs. If set to a credential-free `http://host:port` endpoint and network access is on, the harness checks that the proxy accepts a TCP connection before starting and before each role. It injects HTTP(S) proxy variables through Codex's `shell_environment_policy.set` for spawned shell commands, while removing inherited proxy variables from the Codex/API process environment for that run. It does not set a global proxy, proxy Codex/OpenAI/DeepSeek API traffic, or silently switch to direct access if the configured proxy is unavailable. Tools may ignore HTTP proxy variables, and this is not a firewall or universal traffic interception. Raw child event and stderr files can contain sensitive task data. For HTTPS interception through Caido, the agent's target-access tool must trust the Caido certificate; configure trust for that tool in the isolated environment if needed. Do not disable TLS verification or install a global CA as a workaround. Codex web search and non-shell tools are outside this proxy setting. See [Codex configuration reference](https://developers.openai.com/codex/config-reference) for the shell environment setting.

## Archive and restore case data

`archive` moves both case inputs and run history for one category, or for all categories only when explicitly requested. It previews by default; `--confirm` performs the move. It never deletes challenge data. The archive is placed in `archives/<timestamp-id>/`, with `manifest.json` listing every original and archived path. `archives/` is ignored by Git. After a successful move, selected `categories/<category>/cases/` and `runs/` are empty and usable. Personal `.local/` settings, tools, skills, source, `.venv/`, and Git history are untouched.

```sh
./ctf-start archive --category web --dry-run
./ctf-start archive --category web --confirm
./ctf-start archive --all-categories --dry-run   # review every category first
./ctf-start archive --all-categories --confirm   # only after reviewing that plan
./ctf-start archives
./ctf-start restore --archive-id <ID_FROM_ARCHIVES> --dry-run
./ctf-start restore --archive-id <ID_FROM_ARCHIVES> --confirm
```

Restore refuses to overwrite any nonempty active case or run directory. Archive and restore refuse a category while a run from this launcher is active; init and seal use the same category lock. A process started with an older launcher may not hold this lock, so finish old runs first. Symlinks in selected data are rejected. If an interrupted move cannot be rolled back, the tool leaves `archives/.pending-<id>/manifest.json` and any moved data in place for manual recovery; inspect that folder and the active paths before retrying. There is no purge command.

## Source map and publication

See the instruction map ([English](docs/INSTRUCTION-MAP.md) | [日本語](docs/INSTRUCTION-MAP.ja.md)) for all seven `AGENTS.md` and skill paths, plus generated role files. Upstream source and the MIT notice are documented in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). Python category packages are declared in pyproject.toml and pinned by uv.lock; uv sync --locked installs the selected default groups into the project .venv. Native tools are checked separately.

If you are publishing a new source-only copy, review the source, create an empty GitHub repository under your account, then run these commands locally. Replace the URL with your own repository. If you have already pushed this project, keep its existing Git repository and remote; skip `git init` and `git remote add origin`. Nothing is uploaded by running the harness itself.

```sh
cd ~/ctf/ctf-harness
git init -b main
git status --short
git ls-files --others --exclude-standard
git check-ignore -v categories/crypto/cases/sample/input/problem.txt
git add -n .                    # inspect every proposed source path
git add .
git commit -m 'Initial CTF harness'
git remote add origin https://github.com/<OWNER>/<REPO>.git
git push -u origin main
```

Do not force-add ignored files. `.gitignore` cannot remove a secret already committed to history, so use a new source-only repository if that ever happens. For an existing repository, review `git status --short` and `git add -n .` before committing documentation changes and pushing to its existing remote.

To later make this the owner's `~/ctf/daybreak-blue`, follow [docs/MIGRATION.md](docs/MIGRATION.md) after the new repository and fresh clone have been reviewed. This handoff has **not** moved or deleted the old project.

### Category Python environment and candidate evidence

Run `uv sync --locked` after cloning or pulling dependency changes. `./ctf-start` uses `uv run --offline --locked`; generated roles use `uv run --no-cache --offline --locked --no-sync python` from their role directory. Default groups keep all declared categories available. Do not install packages during a challenge. Explicit packages: Web `httpx`, `beautifulsoup4`, `lxml`; Crypto `pycryptodome`, `sympy`; Pwn `pwntools`; Reverse `z3-solver`, `capstone`, `pyelftools`, `pefile`; Forensics `Pillow`, `scapy`, `exifread`, `pypdf`; OSINT `dnspython`; Misc `regex`. Exact versions and transitive dependencies are pinned in `uv.lock`. Native tools are separate from Python imports.

Every run writes `candidates.json` and `CANDIDATES.md`, including disagreement and partial failures. Exact candidate strings retain their role, reported basis, report path and artifact paths. `memory_hypothesis` identifies a role report that describes a recalled or guessed answer. Every basis remains unverified by the harness; the review role sees frozen prior reports and is not independent evidence. `candidate.txt` retains the existing consensus or owner-confirmed output. `reference-assisted` requires an observed completed external search or successful shell command to a non-target URL; a challenge URL alone does not cause it. Observed tool access does not prove the report used that data. External URLs declared without observed access are labeled `external-reference-declared-unverified`.

With a configured active proxy, `result.json` records per-role HTTP 400, HTTP 502 and connection-refused observations without copying response bodies. Shell exit code zero can coexist with an HTTP error. Counts alone cannot prove which side generated a 400 or why the upstream refused a connection. Check raw events and proxy logs privately before changing a request or target. A local loopback fixture covers HEAD, GET, large GET and two parallel GETs; historical failures can still depend on request shape or instance lifetime.
`./ctf-start tools --category reverse --missing-only --json` lists Python imports, native executables and REA/Ghidra readiness without installing anything. Omit `--category` to inspect every category. `available`, `missing`, `misconfigured`, `incompatible` and `untested` have distinct meanings; optional native tools can remain missing until needed.
The checker shows current tool checks only; saved historical REA/Codex test results stay in the ignored run directories and are never listed by `tools`. `available` for a binary means its version command launched, not that every operation or sandbox profile was tested.

For reverse cases, the harness requests the project-local `rea-static` interface to REA/Ghidra and stops before model launch if its pinned native tools are missing. See [local setup and scope](docs/REA-GHIDRA.md). REA is used through the guarded CLI in the role shell; the broad MCP server is not registered. On this host, an actual Codex child with sandbox network off could not start Ghidra's local Unix socket bridge. One approved, network-on child test decompiled a harmless self-built ELF; this does not enable network persistently or prove another profile works.

`--no-proxy` is a one-run override that clears inherited HTTP(S), ALL and NO proxy variables in the Codex process and its spawned shells. It can change the Codex API's routing for that invocation; it does not alter global settings. See [the Caido investigation](docs/CAIDO-INVESTIGATION.md) for observed historical HTTP errors and the limits of the local reproduction.

For native Pwn and Forensics tools on Ubuntu 26.04 x86-64 WSL, run `./scripts/setup-native-tools.sh`, then `./ctf-start tools --missing-only --json` and `uv run --offline --locked --no-sync python scripts/native_smoke.py`. This installs GDB, socat, ExifTool, TShark, Binwalk v3, 7-Zip and unzip in ignored `.local/tools/` without sudo. Role shells get the local tool directory on PATH; the parent Codex API environment is not changed. See [native-tool capabilities and limitations](docs/NATIVE-TOOLS.md).

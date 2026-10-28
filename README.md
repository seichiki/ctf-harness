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
./ctf-start list
./ctf-start init --category crypto --case-id sample --scope-note 'My authorized local CTF problem'
# Put only that case's supplied files in categories/crypto/cases/sample/input/
./ctf-start seal --category crypto --case-id sample
./ctf-start run --category crypto --case-id sample --preset test --dry-run
./ctf-start run --category crypto --case-id sample --preset test
```

`setup` writes only `.local/config.toml`, which Git ignores. It stores a model ID, effort, Daybreak choice, orchestration choice, and `network_access = "off"` or `"on"`; it does **not** copy authentication. Existing local configs without `network_access` default to off. If you already have a local config, edit it directly after reviewing `config.example.toml`. The default effort is `medium`; choose another supported effort for your model as needed. A model name in this file does not grant access. The `run` command also accepts `--model`, `--effort`, `--daybreak`, `--orchestration`, and `--network-access off|on` overrides, all applied to every session in that run.

Owner example, kept private in `.local/config.toml`: `./ctf-start setup --model gpt-5.6-sol --effort high --daybreak blue --orchestration multi`. This is optional; a friend without Blue can keep `--daybreak off` and use their own available model. If the selected model/effort/program fails, the run records the error and stops; it never chooses a different one silently.

## Modes and controls

`--orchestration single` makes one fresh CLI session and is the public default. `--orchestration multi` runs an initial verifier, two independent solver sessions in parallel, and a separate frozen-report review. The sessions are separate CLI processes, not native subagents. `--orchestration interactive` opens one fresh terminal session without submitting a challenge prompt. For interactive Blue, the documented `daybreak=true` setting is requested; select the visible **Daybreak Blue** item in `/model` before typing the challenge. This manual selection is recorded as user-confirmed or unknown, never as verified server application. Off mode explicitly sets `daybreak=false` and a non-Blue model. Noninteractive off additionally requests `--cyber-access-program standard`; Blue mode requests `daybreak_blue` on each `codex exec`. Global user config is ignored for noninteractive runs, while the existing ChatGPT login is retained. API-key environment variables are removed from child Codex processes.

`--preset test` defaults to similar-search off and answer reference off. `--preset production` defaults to similar-search on and answer reference off. Use `--similar-search on|off` independently of the preset. Use `--answer-reference on --answer-file /path/to/reference` only when you intend that file to be available to every role. Each change creates a fresh run folder. Search on uses built-in Codex web search and the local `ctf-similar-search` adapter; no Tavily key or additional API is needed. Search off sets `web_search=disabled` and omits that adapter from the role directory. Search and answer-reference switches do not change sandbox outbound network access. Runs and cases are ignored by Git, but directory separation does not prevent OS-level reads of other accessible files.

Sandbox outbound network access defaults to off for every preset. For one authorized live case, use `./ctf-start run --category web --case-id <fresh-case-id> --preset test --network-access on --dry-run`, then repeat without `--dry-run` after checking the plan. This requests `sandbox_workspace_write.network_access=true` for each role; off explicitly requests `false`. **On is not limited to the case host**: the target in the case manifest is an instruction, not a network firewall. Dry-run, `settings.json`, and `result.json` record the requested choice; they do not prove effective network enforcement. The harness requests `approval_policy=on-request`, but Codex CLI 0.164.0 has been observed displaying `approval: never` for a noninteractive `codex exec`; do not rely on an approval prompt during external runs. The workspace-write sandbox remains selected, and failures do not trigger a less restrictive fallback.

Each case has a 1–15 minute deadline for external runs. The launcher records prompts, CLI flags, JSONL events, usage when supplied, source URLs, and a candidate hash. `candidate_pending` means **you** still need to verify the candidate. Unknown challenge binaries/scripts must not run on the host; use a separately approved isolation environment. There is no automatic flag submission.

## Source map and publication

See the instruction map ([English](docs/INSTRUCTION-MAP.md) | [日本語](docs/INSTRUCTION-MAP.ja.md)) for all seven `AGENTS.md` and skill paths, plus generated role files. Upstream source and the MIT notice are documented in [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). Python is dependency-free and locked with uv; category-specific tools are optional and must be installed separately only if a chosen challenge requires them.

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

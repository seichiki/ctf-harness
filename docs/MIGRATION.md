# Later migration to `~/ctf/daybreak-blue`

This is a plan only. The current original project is preserved; no move, replacement, deletion, clone from GitHub, or upload has been performed.

1. Review the source-only `~/ctf/ctf-harness` tree, `docs/INSTRUCTION-MAP.md`, `.gitignore`, and the temporary-copy result from `uv run --offline --locked python tools/check_clone.py`. Confirm the desired GitHub repository contains only this harness source. A model or Blue entitlement is not verified by that test.
2. Publish the reviewed source to a new repository using your own GitHub account. The source folder has no `.git` yet; initialize it as shown in `README.md`. Before committing, inspect `git status --short`, `git ls-files --others --exclude-standard`, and `git add -n .`. Keep `.local/`, `categories/*/cases/`, `categories/*/runs/`, answers, auth, and historical files out of Git.
3. After the GitHub clone URL exists and a fresh clone has passed `./ctf-start doctor` and the offline tests, choose a unique dated backup folder under `~/ctf`. Verify that destination does not already exist. Move the current `daybreak-blue` folder to that backup, then clone the new repository into `~/ctf/daybreak-blue`. Do not delete the backup.
4. In the new clone, run `uv sync --locked`, confirm your own `codex login status`, and create a new ignored `.local/config.toml` with `./ctf-start setup`. Your ChatGPT credentials remain in your normal Codex sign-in location; do not copy an auth file into the repository. Start with a dry-run case before any challenge.
5. Keep old inputs and runs only in the backup. If you later want a specific case, import it deliberately into a new ignored case directory and reseal its hashes. Do not bulk-copy old results, answers, `.codex`, or session histories into the public clone.

If cloning or setup fails after the move, keep the dated backup intact and restore it to its original name only after checking the destination path and preserving any new work in the failed clone. No recursive deletion is needed for this plan.

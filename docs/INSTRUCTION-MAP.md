# Instruction and configuration map

The root `AGENTS.md` applies to every case. Each category adds its own `AGENTS.md` and discoverable `.agents/skills/ctf-<category>/SKILL.md`. An adapter instructs Codex to open the pinned upstream Markdown reference when relevant; upstream files under `third_party/` are not themselves active skills.

| Category | Category instructions | Discoverable adapter | Pinned reference |
| --- | --- | --- | --- |
| web | `categories/web/AGENTS.md` | `categories/web/.agents/skills/ctf-web/SKILL.md` | `third_party/ctf-skills/ctf-web/SKILL.md` |
| crypto | `categories/crypto/AGENTS.md` | `categories/crypto/.agents/skills/ctf-crypto/SKILL.md` | `third_party/ctf-skills/ctf-crypto/SKILL.md` |
| pwn | `categories/pwn/AGENTS.md` | `categories/pwn/.agents/skills/ctf-pwn/SKILL.md` | `third_party/ctf-skills/ctf-pwn/SKILL.md` |
| reverse | `categories/reverse/AGENTS.md` | `categories/reverse/.agents/skills/ctf-reverse/SKILL.md` | `third_party/ctf-skills/ctf-reverse/SKILL.md` |
| forensics | `categories/forensics/AGENTS.md` | `categories/forensics/.agents/skills/ctf-forensics/SKILL.md` | `third_party/ctf-skills/ctf-forensics/SKILL.md` |
| osint | `categories/osint/AGENTS.md` | `categories/osint/.agents/skills/ctf-osint/SKILL.md` | `third_party/ctf-skills/ctf-osint/SKILL.md` |
| misc | `categories/misc/AGENTS.md` | `categories/misc/.agents/skills/ctf-misc/SKILL.md` | `third_party/ctf-skills/ctf-misc/SKILL.md` |

`config.example.toml` shows the portable local settings. `./ctf-start setup` writes ignored `.local/config.toml`; no account's model or Blue permission is embedded in public source. `harness/config.py` validates configuration, `harness/runner.py` builds explicit CLI commands, `harness/report.py` validates evidence and artifact paths, and `harness/cli.py` supplies the menu and subcommands. `docs/report.schema.json` is the structured report template.

External runs use `-C categories/<category>/runs/<case>/<run>/<role>`. `harness/runner.py` composes the shared and role-specific prompts and saves them as role-local `prompt.txt`; it saves the actual options without the prompt in `invocation.json`. Single mode has `solver`. Multi mode has `verifier`, `solver_a`, `solver_b`, and `verifier_review`; only the last receives `frozen-reports.json`. A run-level `settings.json`, `output-schema.json`, and `result.json` record choices, input schema, and final candidate status. Agent `events.jsonl`, `run.json`, and `structured-report.json` remain in ignored run areas.

Interactive mode creates `.../<run>/interactive/`, copies only the selected input and optional explicit reference, and writes the selected rules to a role-local `AGENTS.md`. `invocation.json` contains a prompt-free terminal command. The user chooses the Blue menu item manually when Blue is requested. The run-level settings record that choice as a user report, not server proof.

Test defaults search/reference off; production defaults search on/reference off. `--similar-search on` copies `skill_templates/ctf-similar-search/SKILL.md` to the run-local `.agents/skills/ctf-similar-search/SKILL.md` and sets `web_search=live`. Off omits the run-local adapter and sets `web_search=disabled`. `--answer-reference on --answer-file PATH` copies the explicitly selected file to role-local `reference/answer.txt`; off copies none. Every mode change receives fresh CLI sessions and a new run folder. No case input, answer, role output, or local account config belongs in Git.

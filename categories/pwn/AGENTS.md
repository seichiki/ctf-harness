# Pwn CTF workspace

Use the project-local `ctf-pwn` skill and the explicitly selected case only. The root AGENTS.md supplies shared model, approval, sandbox, and scope rules.

The launcher records test/production mode, public-search setting, and answer-reference setting for each fresh run. Follow those settings in every role. Search off means no public writeup search; search on allows it and requires source URLs. An answer file is available only when explicitly selected for that run; mark answer-informed results.

Use `uv run --offline --locked python` for self-authored Python. Do not run unknown challenge code or bundled upstream scripts on the WSL/Windows host, install packages automatically, or submit a flag. Restrict live traffic to the explicitly authorized target.

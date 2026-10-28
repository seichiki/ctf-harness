"""Local uv launcher; no model call occurs for setup, doctor, init, seal, or dry-run."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness.config import DAYBREAK, EFFORTS, ORCHESTRATION, ROOT, load, save, validate
from harness.runner import (
    CATEGORIES, SOURCE_REVISION, build_tui_command, case_dir, category_dir,
    choose_switches, common_prompt, init_case, load_case, prepare_role,
    require_chatgpt_login, resolve_reference, run_external, scrub_api_environment,
    seal_case, utc_now,
)


def doctor() -> dict:
    codex = shutil.which("codex")
    uv = shutil.which("uv")
    version = "missing"
    blue_exec_selector = False
    isolated_exec_config = False
    if codex:
        result = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=10, check=False)
        version = result.stdout.strip() if result.returncode == 0 else "unavailable"
        help_result = subprocess.run([codex, "exec", "--help"], capture_output=True, text=True, timeout=10, check=False)
        blue_exec_selector = "--cyber-access-program" in help_result.stdout and "daybreak_blue" in help_result.stdout
        isolated_exec_config = "--ignore-user-config" in help_result.stdout and "standard" in help_result.stdout
    missing_skills = [name for name in CATEGORIES if not (category_dir(name) / ".agents" / "skills" / f"ctf-{name}" / "SKILL.md").is_file()]
    return {"uv": "present" if uv else "missing", "codex_version": version,
            "exec_cyber_selector": blue_exec_selector,
            "exec_user_config_isolation": isolated_exec_config,
            "lockfile": (ROOT / "uv.lock").is_file(),
            "third_party_license": (ROOT / "third_party" / "ctf-skills" / "LICENSE").is_file(),
            "missing_category_skills": missing_skills,
            "auth_status": "not inspected; actual run requires ChatGPT login status",
            "model_catalog": "not inspected; choose a model available to your own account"}


def run_interactive(category: str, case_id: str, config: dict, switches: dict,
                    answer_file: Path | None, answer_hash: str | None) -> Path:
    case_path, case = load_case(category, case_id)
    codex = shutil.which("codex")
    if not codex:
        raise ValueError("Codex CLI is missing")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("interactive mode requires a terminal; use --dry-run to inspect settings")
    require_chatgpt_login(codex)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = category_dir(category) / "runs" / case_id / f"{stamp}-interactive-{uuid.uuid4().hex[:6]}"
    run_root.mkdir(parents=True, exist_ok=False)
    role_dir = prepare_role(run_root, "interactive", case_path / "input", switches, answer_file)
    web_mode = "live" if switches["similar_search"] else "disabled"
    rules = common_prompt(category, case_id, case, switches)
    (role_dir / "AGENTS.md").write_text(
        "# Current interactive case\n\n" + rules + "\n\n"
        + ("Before asking about the challenge, select `/model` → `Daybreak Blue` and check `/daybreak` is On. "
           "The launcher does not know a Blue model ID.\n" if config["daybreak"] == "blue" else
           "Daybreak is explicitly Off for this run. Use the selected non-Blue model.\n"),
        encoding="utf-8",
    )
    command = build_tui_command(config, role_dir, web_mode, codex)
    record = {**config, **switches, "category": category, "case_id": case_id, "created_at": utc_now(),
              "answer_reference_sha256": answer_hash, "web_search_mode": web_mode,
              "blue_model_selection": "unknown" if config["daybreak"] == "blue" else "not_requested",
              "server_daybreak_applied": "unverified", "initial_challenge_prompt": None,
              "upstream_ctf_skills_revision": SOURCE_REVISION}
    settings_file = run_root / "settings.json"
    settings_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (role_dir / "invocation.json").write_text(json.dumps({"argv": command, "prompt": None}, indent=2) + "\n", encoding="utf-8")
    if config["daybreak"] == "blue":
        print("Daybreak is requested On. Before sending a challenge, select /model → Daybreak Blue and check /daybreak.")
    else:
        print("Daybreak is explicitly Off; the selected account model is used. No challenge prompt was sent.")
    try:
        result = subprocess.run(command, cwd=role_dir, env=scrub_api_environment(), check=False)
        record["exit_code"] = result.returncode
    finally:
        record["ended_at"] = utc_now()
        if config["daybreak"] == "blue" and sys.stdin.isatty():
            if input("Did you select /model → Daybreak Blue? [y/N]: ").strip().lower() in ("y", "yes"):
                record["blue_model_selection"] = "user_confirmed"
        settings_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"Session settings: {settings_file}")
    return run_root


def menu() -> list[str]:
    print("CTF harness — setup, doctor, init, seal, run, list")
    action = input("Action: ").strip().lower()
    if action in ("doctor", "list"):
        return [action]
    if action == "setup":
        model = input("Exact model ID available to your Codex account: ").strip()
        effort = input("Effort [medium]: ").strip().lower() or "medium"
        daybreak = input("Daybreak [off/blue, default off]: ").strip().lower() or "off"
        orchestration = input("Orchestration [single/multi/interactive, default single]: ").strip().lower() or "single"
        return ["setup", "--model", model, "--effort", effort, "--daybreak", daybreak,
                "--orchestration", orchestration]
    if action not in ("init", "seal", "run"):
        raise ValueError("unknown action")
    category = input("Category: ").strip().lower()
    case_id = input("Case ID: ").strip().lower()
    args = [action, "--category", category, "--case-id", case_id]
    if action == "init":
        args += ["--scope-note", input("Authorized scope note: ").strip()]
    if action == "run":
        model = input("Model override [use local config]: ").strip()
        effort = input("Effort override [use local config]: ").strip().lower()
        daybreak = input("Daybreak override [off/blue, use local config]: ").strip().lower()
        orchestration = input("Orchestration override [single/multi/interactive, use local config]: ").strip().lower()
        for key, value in (("model", model), ("effort", effort), ("daybreak", daybreak), ("orchestration", orchestration)):
            if value:
                args += [f"--{key}", value]
        args += ["--preset", input("Preset [test]: ").strip().lower() or "test"]
        args += ["--similar-search", input("Similar search [auto/on/off]: ").strip().lower() or "auto"]
        answer = input("Answer reference [auto/on/off]: ").strip().lower() or "auto"
        args += ["--answer-reference", answer]
        if answer == "on":
            args += ["--answer-file", input("Explicit answer file path: ").strip()]
        if (input("Dry-run only? [Y/n]: ").strip().lower() or "y") != "n":
            args.append("--dry-run")
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ctf-start", description="Account-configured CTF harness")
    sub = parser.add_subparsers(dest="action")
    setup = sub.add_parser("setup", help="save private local model choices; does not manage authentication")
    setup.add_argument("--model", required=True)
    setup.add_argument("--effort", choices=EFFORTS, default="medium")
    setup.add_argument("--daybreak", choices=DAYBREAK, default="off")
    setup.add_argument("--orchestration", choices=ORCHESTRATION, default="single")
    sub.add_parser("doctor", help="check local CLI/uv/source presence without model requests")
    sub.add_parser("list", help="list category names and case IDs")
    init = sub.add_parser("init", help="create empty case input directory")
    init.add_argument("--category", choices=CATEGORIES, required=True)
    init.add_argument("--case-id", required=True)
    init.add_argument("--scope-note", required=True)
    init.add_argument("--time-limit-minutes", type=int, default=15)
    init.add_argument("--target")
    seal = sub.add_parser("seal", help="record input file hashes")
    seal.add_argument("--category", choices=CATEGORIES, required=True)
    seal.add_argument("--case-id", required=True)
    run = sub.add_parser("run", help="start a fresh run, or inspect a dry-run plan")
    run.add_argument("--category", choices=CATEGORIES, required=True)
    run.add_argument("--case-id", required=True)
    run.add_argument("--model")
    run.add_argument("--effort", choices=EFFORTS)
    run.add_argument("--daybreak", choices=DAYBREAK)
    run.add_argument("--orchestration", choices=ORCHESTRATION)
    run.add_argument("--preset", choices=("test", "production"), default="test")
    run.add_argument("--similar-search", choices=("auto", "on", "off"), default="auto")
    run.add_argument("--answer-reference", choices=("auto", "on", "off"), default="auto")
    run.add_argument("--answer-file")
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(menu() if argv is None and len(sys.argv) == 1 else argv)
    try:
        if args.action == "setup":
            path = save(validate({"model": args.model, "effort": args.effort,
                                  "daybreak": args.daybreak, "orchestration": args.orchestration}))
            print(f"Saved local choices: {path}; model availability is account-dependent and not yet verified")
        elif args.action == "doctor":
            print(json.dumps(doctor(), indent=2))
        elif args.action == "list":
            print(json.dumps({name: sorted(p.name for p in (category_dir(name) / "cases").iterdir() if p.is_dir())
                              if (category_dir(name) / "cases").is_dir() else [] for name in CATEGORIES}, indent=2))
        elif args.action == "init":
            print(init_case(args.category, args.case_id, args.scope_note, args.time_limit_minutes, args.target))
        elif args.action == "seal":
            print(json.dumps(seal_case(args.category, args.case_id), indent=2))
        elif args.action == "run":
            config = load({key: getattr(args, key) for key in ("model", "effort", "daybreak", "orchestration")})
            switches = choose_switches(args.preset, args.similar_search, args.answer_reference)
            case_path, case = load_case(args.category, args.case_id)
            answer_file, answer_hash = resolve_reference(switches, args.answer_file, args.dry_run)
            plan = {**config, **switches, "category": args.category, "case_id": args.case_id,
                    "case_dir": str(case_path), "input_file_count": len(case["input_sha256"]),
                    "answer_file_supplied": answer_file is not None,
                    "web_search_config": "live" if switches["similar_search"] else "disabled",
                    "search_skill": "run-local" if switches["similar_search"] else "absent",
                    "auth": "existing ChatGPT Codex sign-in; no API fallback",
                    "model_availability": "account-dependent, unverified",
                    "daybreak_server_applied": "unverified", "network_isolation": False}
            if args.dry_run:
                print(json.dumps(plan, indent=2))
            elif config["orchestration"] == "interactive":
                run_interactive(args.category, args.case_id, config, switches, answer_file, answer_hash)
            else:
                run_external(args.category, args.case_id, config, switches, answer_file, answer_hash)
        else:
            parser.print_help()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

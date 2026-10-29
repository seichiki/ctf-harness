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

from harness.archive import archive_categories, list_archives, restore_archive
from harness.config import DAYBREAK, EFFORTS, NETWORK_ACCESS, ORCHESTRATION, ROOT, load, public_settings, save, validate
from harness.locks import category_lock
from harness.handoff import Handoff
from harness.runner import (
    CATEGORIES, SOURCE_REVISION, build_tui_command, case_dir, category_dir,
    choose_switches, common_prompt, init_case, load_case, prepare_role,
    redact_proxy_command, require_chatgpt_login, resolve_reference, run_external, scrub_api_environment,
    require_proxy_available, seal_case, utc_now,
    require_rea_available,
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
    with category_lock(category, ROOT):
        return _run_interactive(category, case_id, config, switches, answer_file, answer_hash)


def _run_interactive(category: str, case_id: str, config: dict, switches: dict,
                     answer_file: Path | None, answer_hash: str | None) -> Path:
    case_path, case = load_case(category, case_id)
    require_rea_available(category)
    codex = shutil.which("codex")
    if not codex:
        raise ValueError("Codex CLI is missing")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("interactive mode requires a terminal; use --dry-run to inspect settings")
    require_proxy_available(config)
    require_chatgpt_login(codex, bool(config["proxy_url"]) or bool(config.get("proxy_override_off")))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = category_dir(category) / "runs" / case_id / f"{stamp}-interactive-{uuid.uuid4().hex[:6]}"
    run_root.mkdir(parents=True, exist_ok=False)
    try:
        handoff = Handoff(run_root, case, public_settings(config))
        handoff.event("run", "Interactive session prepared; challenge prompt was not automatically sent")
    except Exception:
        handoff = None
    role_dir = prepare_role(run_root, "interactive", case_path / "input", switches, answer_file)
    web_mode = "live" if switches["similar_search"] else "disabled"
    rules = common_prompt(category, case_id, case, switches, config)
    (role_dir / "AGENTS.md").write_text(
        "# Current interactive case\n\n" + rules + "\n\n"
        + ("Before asking about the challenge, select `/model` → `Daybreak Blue` and check `/daybreak` is On. "
           "The launcher does not know a Blue model ID.\n" if config["daybreak"] == "blue" else
           "Daybreak is explicitly Off for this run. Use the selected non-Blue model.\n"),
        encoding="utf-8",
    )
    command = build_tui_command(config, role_dir, web_mode, codex)
    record = {**public_settings(config), **switches, "category": category, "case_id": case_id, "created_at": utc_now(),
              "answer_reference_sha256": answer_hash, "web_search_mode": web_mode,
              "network_access_requested": config["network_access"] == "on",
              "network_access_effective": "unverified", "network_host_restriction": False,
              "approval_policy_requested": "on-request", "approval_policy_effective": "unverified",
              "blue_model_selection": "unknown" if config["daybreak"] == "blue" else "not_requested",
              "server_daybreak_applied": "unverified", "initial_challenge_prompt": None,
              "upstream_ctf_skills_revision": SOURCE_REVISION}
    settings_file = run_root / "settings.json"
    settings_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (role_dir / "invocation.json").write_text(json.dumps({"argv": redact_proxy_command(command), "prompt": None}, indent=2) + "\n", encoding="utf-8")
    if config["daybreak"] == "blue":
        print("Daybreak is requested On. Before sending a challenge, select /model → Daybreak Blue and check /daybreak.")
    else:
        print("Daybreak is explicitly Off; the selected account model is used. No challenge prompt was sent.")
    session_status = "interrupted"
    try:
        result = subprocess.run(command, cwd=role_dir,
                                env=scrub_api_environment(bool(config["proxy_url"]) or bool(config.get("proxy_override_off"))), check=False)
        record["exit_code"] = result.returncode
        session_status = "completed" if result.returncode == 0 else "tool_failure"
    finally:
        record["ended_at"] = utc_now()
        if config["daybreak"] == "blue" and sys.stdin.isatty():
            try:
                selected = input("Did you select /model → Daybreak Blue? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                selected = ""
            if selected in ("y", "yes"):
                record["blue_model_selection"] = "user_confirmed"
        settings_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        if handoff is not None:
            try:
                handoff.finish(session_status)
            except Exception:
                pass
    print(f"Session settings: {settings_file}")
    return run_root


def menu() -> list[str]:
    print("CTF harness — setup, doctor, init, seal, run, list, archive, archives, restore")
    action = input("Action: ").strip().lower()
    if action in ("doctor", "list", "archives"):
        return [action]
    if action == "archive":
        scope = input("Category name or all: ").strip().lower()
        args = ["archive", "--all-categories"] if scope == "all" else ["archive", "--category", scope]
        if input("Type ARCHIVE to move case and run data (Enter previews): ").strip() == "ARCHIVE":
            args.append("--confirm")
        return args
    if action == "restore":
        archive_id = input("Archive ID: ").strip()
        args = ["restore", "--archive-id", archive_id]
        if input("Type RESTORE to move archived data back (Enter previews): ").strip() == "RESTORE":
            args.append("--confirm")
        return args
    if action == "setup":
        model = input("Exact model ID available to your Codex account: ").strip()
        effort = input("Effort [medium]: ").strip().lower() or "medium"
        daybreak = input("Daybreak [off/blue, default off]: ").strip().lower() or "off"
        orchestration = input("Orchestration [single/multi/interactive, default single]: ").strip().lower() or "single"
        network_access = input("Outbound network [off/on, default off]: ").strip().lower() or "off"
        progress = input("Live progress [off/on, default off]: ").strip().lower() or "off"
        proxy_url = input("Optional HTTP proxy URL [none]: ").strip()
        if progress not in ("off", "on"):
            raise ValueError("Live progress must be off or on")
        return ["setup", "--model", model, "--effort", effort, "--daybreak", daybreak,
                "--orchestration", orchestration, "--network-access", network_access,
                *(["--progress"] if progress == "on" else []),
                *(["--proxy", proxy_url] if proxy_url else [])]
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
        network_access = input("Outbound network override [off/on, use local config]: ").strip().lower()
        for key, value in (("model", model), ("effort", effort), ("daybreak", daybreak),
                           ("orchestration", orchestration), ("network-access", network_access)):
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
    args_list = sys.argv[1:] if argv is None else argv
    if args_list[:2] == ["tools", "install"]:
        from harness import toolinstall
        return toolinstall.main(args_list[2:])
    if not args_list:
        from harness.wizard import run_wizard
        return run_wizard(interactive_runner=run_interactive)
    parser = argparse.ArgumentParser(prog="ctf-start", description="Account-configured CTF harness")
    sub = parser.add_subparsers(dest="action")
    setup = sub.add_parser("setup", help="save private local model choices; does not manage authentication")
    setup.add_argument("--model", required=True)
    setup.add_argument("--effort", choices=EFFORTS, default="medium")
    setup.add_argument("--daybreak", choices=DAYBREAK, default="off")
    setup.add_argument("--orchestration", choices=ORCHESTRATION, default="single")
    setup.add_argument("--network-access", choices=NETWORK_ACCESS, default="off")
    setup.add_argument("--progress", action="store_true")
    setup.add_argument("--proxy", dest="proxy_url", default="")
    sub.add_parser("doctor", help="check local CLI/uv/source presence without model requests")
    tools = sub.add_parser(
        "tools", help="category tool inventory; tools install opens the installer",
        epilog="Display labels: WEB=web, CRY=crypto, PWN=pwn, REV=reverse, "
               "FOR=forensics, OSI=osint, MSC=misc, ALL=all categories. "
               "CLI --category and JSON keep canonical names. "
               "Run 'ctf-start tools install [--all|--required]' to install missing tools.")
    tools.add_argument("--category", choices=CATEGORIES)
    tools.add_argument("--missing-only", action="store_true")
    tools.add_argument("--json", action="store_true")
    sub.add_parser("list", help="list category names and case IDs")
    archive = sub.add_parser("archive", help="preview or move selected cases and runs into archives/")
    scope = archive.add_mutually_exclusive_group(required=True)
    scope.add_argument("--category", choices=CATEGORIES)
    scope.add_argument("--all-categories", action="store_true")
    mode = archive.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    mode.add_argument("--confirm", action="store_true", help="execute the previewed archive move")
    sub.add_parser("archives", help="list archived and incomplete archive folders")
    restore = sub.add_parser("restore", help="preview or restore an archive into empty active paths")
    restore.add_argument("--archive-id", required=True)
    restore_mode = restore.add_mutually_exclusive_group()
    restore_mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    restore_mode.add_argument("--confirm", action="store_true", help="restore if active paths are empty")
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
    run.add_argument("--network-access", choices=NETWORK_ACCESS)
    progress_group = run.add_mutually_exclusive_group()
    progress_group.add_argument("--progress", dest="progress", action="store_true",
                                help="show safe live status on stderr")
    progress_group.add_argument("--no-progress", dest="progress", action="store_false")
    run.set_defaults(progress=None)
    proxy_group = run.add_mutually_exclusive_group()
    proxy_group.add_argument("--proxy", dest="proxy_url", help="HTTP proxy for agent shell tools only")
    proxy_group.add_argument("--no-proxy", dest="proxy_url", action="store_const", const="")
    run.add_argument("--quiet", action="store_true", help="suppress startup status and live progress")
    run.add_argument("--owner-confirmation", action="store_true",
                     help="allow this terminal's user to confirm a submitted candidate and stop early")
    run.add_argument("--preset", choices=("test", "production"), default="test")
    run.add_argument("--similar-search", choices=("auto", "on", "off"), default="auto")
    run.add_argument("--answer-reference", choices=("auto", "on", "off"), default="auto")
    run.add_argument("--answer-file")
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(args_list)
    try:
        if args.action == "setup":
            path = save(validate({"model": args.model, "effort": args.effort,
                                  "daybreak": args.daybreak, "orchestration": args.orchestration,
                                  "network_access": args.network_access,
                                  "progress": args.progress, "proxy_url": args.proxy_url}))
            print(f"Saved local choices: {path}; model availability is account-dependent and not yet verified")
        elif args.action == "doctor":
            print(json.dumps(doctor(), indent=2))
        elif args.action == "tools":
            from harness import toolcheck
            check_args = (["--category", args.category] if args.category else [])
            if args.missing_only:
                check_args.append("--missing-only")
            if args.json:
                check_args.append("--json")
            return toolcheck.main(check_args)
        elif args.action == "list":
            print(json.dumps({name: sorted(p.name for p in (category_dir(name) / "cases").iterdir() if p.is_dir())
                              if (category_dir(name) / "cases").is_dir() else [] for name in CATEGORIES}, indent=2))
        elif args.action == "archive":
            selected = CATEGORIES if args.all_categories else (args.category,)
            print(json.dumps(archive_categories(ROOT, selected, confirm=args.confirm), indent=2))
        elif args.action == "archives":
            print(json.dumps(list_archives(ROOT), indent=2))
        elif args.action == "restore":
            print(json.dumps(restore_archive(ROOT, args.archive_id, confirm=args.confirm), indent=2))
        elif args.action == "init":
            print(init_case(args.category, args.case_id, args.scope_note, args.time_limit_minutes, args.target))
        elif args.action == "seal":
            print(json.dumps(seal_case(args.category, args.case_id), indent=2))
        elif args.action == "run":
            config = load({key: getattr(args, key) for key in
                           ("model", "effort", "daybreak", "orchestration", "network_access",
                            "progress", "proxy_url")})
            # An explicit --no-proxy also clears inherited proxy variables for this invocation.
            config["proxy_override_off"] = args.proxy_url == ""
            if args.quiet:
                config["progress"] = False
            if args.owner_confirmation and args.quiet:
                raise ValueError("owner confirmation needs visible terminal prompts; remove --quiet")
            if args.owner_confirmation and config["orchestration"] == "interactive":
                raise ValueError("owner confirmation is for external runs, not interactive Codex sessions")
            switches = choose_switches(args.preset, args.similar_search, args.answer_reference)
            case_path, case = load_case(args.category, args.case_id)
            answer_file, answer_hash = resolve_reference(switches, args.answer_file, args.dry_run)
            plan = {**public_settings(config), **switches, "category": args.category, "case_id": args.case_id,
                    "owner_confirmation_requested": args.owner_confirmation,
                    "case_dir": str(case_path), "input_file_count": len(case["input_sha256"]),
                    "answer_file_supplied": answer_file is not None,
                    "web_search_config": "live" if switches["similar_search"] else "disabled",
                    "search_skill": "run-local" if switches["similar_search"] else "absent",
                    "network_access_requested": config["network_access"] == "on",
                    "network_access_effective": "unverified", "network_host_restriction": False,
                    "proxy_effective": ("unverified" if config["proxy_url"] and config["network_access"] == "on" else
                                        "inactive" if config["proxy_url"] else "not_configured"),
                    "approval_policy_requested": "on-request", "approval_policy_effective": "unverified",
                    "auth": "existing ChatGPT Codex sign-in; no API fallback",
                    "model_availability": "account-dependent, unverified",
                    "daybreak_server_applied": "unverified", "network_isolation": False}
            plan["reverse_static_tool"] = "REA/Ghidra via project-local rea-static" if args.category == "reverse" else None
            if args.dry_run:
                print(json.dumps(plan, indent=2))
            else:
                if not args.quiet:
                    print(f"Requested: model={config['model']} effort={config['effort']} "
                          f"daybreak={config['daybreak']} network={config['network_access']} "
                          f"proxy={'on' if plan['proxy_active'] else 'off'} "
                          f"progress={'on' if config['progress'] else 'off'}", file=sys.stderr)
                if config["orchestration"] == "interactive":
                    run_root = run_interactive(args.category, args.case_id, config, switches, answer_file, answer_hash)
                else:
                    run_root = run_external(args.category, args.case_id, config, switches, answer_file, answer_hash,
                                            progress=config["progress"],
                                            **({"owner_confirmation": True} if args.owner_confirmation else {}))
                if not args.quiet and isinstance(run_root, Path):
                    if (run_root / "OWNER_CONFIRMATION.json").is_file():
                        print(f"正解報告：{run_root / 'OWNER_CONFIRMATION.json'}", file=sys.stderr)
                    if (run_root / "SOLUTION.md").is_file():
                        print(f"解法ファイル：{run_root / 'SOLUTION.md'}", file=sys.stderr)
                    if (run_root / "HANDOFF.md").is_file():
                        print(f"引継ぎファイル：{run_root / 'HANDOFF.md'}", file=sys.stderr)
                    print(f"ログ保存先：{run_root}", file=sys.stderr)
        else:
            parser.print_help()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

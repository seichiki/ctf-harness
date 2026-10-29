"""No-argument, new-problem-only wizard with explicit operation confirmation."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from harness import runner
from harness.confirm import ConfirmationCancelled, ask
from harness.config import CATEGORIES, ROOT, load, public_settings
from harness.locks import category_lock
from harness.report import sha256


class Back(Exception):
    pass


class Cancelled(Exception):
    pass


PLACEHOLDERS = {"...", "todo", "tbd", "placeholder", "problem statement",
                "<problem statement>", "問題文", "ここに問題文"}


def _read(input_fn: Callable[[str], str], prompt: str) -> str:
    try:
        value = input_fn(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise Cancelled from exc
    if value.strip().lower() == "/cancel":
        raise Cancelled
    if value.strip().lower() == "/back":
        raise Back
    return value


def _choose(input_fn: Callable[[str], str], heading: str,
            options: tuple[tuple[str, str], ...]) -> str:
    while True:
        print(heading)
        for number, (_, label) in enumerate(options, 1):
            print(f"  {number}. {label}")
        chosen = _read(input_fn, "番号を選択: ").strip().lower()
        if chosen.isdigit() and 1 <= int(chosen) <= len(options):
            return options[int(chosen) - 1][0]
        for key, _ in options:
            if chosen == key:
                return key
        print("表示された番号を選んでください。")


def _problem_name(input_fn: Callable[[str], str]) -> str:
    while True:
        name = _read(input_fn, "問題名（ケース ID は自動生成）: ").strip()
        if name and len(name) <= 120 and not any(unicodedata.category(c).startswith("C") for c in name):
            return name
        print("1行の問題名を120文字以内で入力してください。")


def _new_case_id(root: Path, category: str, name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:32].strip("-") or "case"
    for _ in range(5):
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        case_id = f"{slug}-{suffix}"
        if not (root / "categories" / category / "cases" / case_id).exists():
            return case_id
    raise ValueError("could not generate a unique case ID")


def _scan_files(files_dir: Path) -> dict[str, str]:
    if files_dir.is_symlink() or not files_dir.is_dir():
        raise ValueError("配布ファイルの場所が見つからないか、シンボリックリンクです")
    files = {}
    for path in sorted(files_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError("配布ファイルにシンボリックリンクは使えません")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("通常のファイル以外が含まれています")
        files[path.relative_to(files_dir).as_posix()] = sha256(path)
    return files


def _confirm_files(input_fn: Callable[[str], str], files_dir: Path) -> dict[str, str]:
    while True:
        print(f"配布ファイル保存先：{files_dir}")
        print("Enterで完了")
        if _read(input_fn, ""):
            print("Enter を押してください。")
            continue
        try:
            files = _scan_files(files_dir)
        except ValueError as exc:
            print(f"確認できません: {exc}")
            continue
        if files:
            print("配布ファイル:")
            for name in files:
                print("  " + json.dumps(name, ensure_ascii=True))
        else:
            print("配布ファイルなし")
        return files


def _statement(input_fn: Callable[[str], str]) -> str:
    while True:
        print("問題文を入力してください。複数行可。単独の /end で終了、/back で戻る、/cancel で中止します。")
        lines = []
        while True:
            line = _read(input_fn, "> ")
            if line.strip() == "/end":
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        if text and text.casefold() not in PLACEHOLDERS:
            return text + "\n"
        print("空欄や仮の問題文では進めません。実際の問題文を入力してください。")


def _target(input_fn: Callable[[str], str]) -> str:
    while True:
        value = _read(input_fn, "許可された URL または host:port: ").strip()
        if not value or any(c.isspace() or unicodedata.category(c).startswith("C") for c in value):
            print("空欄・空白を含まない単一の接続先を入力してください。")
            continue
        if "://" in value:
            try:
                parsed = urlsplit(value)
                valid = (parsed.scheme in ("http", "https") and parsed.hostname and
                         parsed.username is None and parsed.password is None and not parsed.fragment)
                _ = parsed.port
            except ValueError:
                valid = False
        else:
            valid = bool(re.fullmatch(r"[A-Za-z0-9.-]+(?::\d{1,5})?", value))
        if valid:
            return value
        print("認証情報・フラグメントを含まない HTTP(S) URL か host:port を指定してください。")


def _minutes(input_fn: Callable[[str], str]) -> int:
    while True:
        value = _read(input_fn, "制限時間（正の整数、Enterで15分）: ").strip()
        if not value:
            return 15
        try:
            minutes = int(value) if value.isascii() and value.isdecimal() else None
        except ValueError:
            minutes = None
        if runner.valid_minutes(minutes):
            return minutes
        print("正の整数（分）を入力してください。")


def _write_statement(path: Path, text: str, previous_hash: str | None) -> str:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("statement.txt は通常のファイルである必要があります")
    if path.exists():
        if previous_hash is None or sha256(path) != previous_hash:
            raise ValueError("statement.txt がウィザードの外で変更されたため上書きしません")
        path.write_text(text, encoding="utf-8")
    else:
        with path.open("x", encoding="utf-8") as target:
            target.write(text)
    return sha256(path)


def _summarize(case: Path, data: dict, config: dict, switches: dict) -> None:
    public = public_settings(config)
    print("\n実行前の確認:")
    print(f"  問題: {data['name']} / {data['category']} / {data['case_id']}")
    print(f"  ケース: {case}")
    print(f"  配布ファイル: {len(data['files'])}件")
    print(f"  接続先: {data['target'] or 'なし（ローカル問題）'}")
    print(f"  許可範囲: {data['scope_note']}")
    print(f"  制限時間: {data['minutes']}分 / プリセット: {switches['preset']}")
    print(f"  類似検索: {'on' if switches['similar_search'] else 'off'} / 正解参照: off")
    print(f"  モデル: {config['model']} / effort: {config['effort']} / Daybreak: {config['daybreak']}")
    print(f"  実行方式: {config['orchestration']} / ネットワーク: {config['network_access']}")
    print(f"  プロキシ: {'on' if public['proxy_active'] else 'off'} / 進行表示: {'on' if config['progress'] else 'off'}")
    if config["orchestration"] == "interactive":
        print("  対話モードでは問題文を自動送信しません。")
    print("実行確認を終えるまでモデルは起動せず、ターゲットにも接続しません。")


def run_wizard(*, root: Path = ROOT, input_fn: Callable[[str], str] | None = None,
               tty: bool | None = None, external_runner=None, interactive_runner=None,
               auto_yes: bool = False) -> int:
    """Create a visible draft immediately; seal and run after operation confirmation."""
    if tty is None:
        tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not tty:
        print("対話端末が必要です。自動処理では明示的なサブコマンドを使ってください。", file=sys.stderr)
        return 2
    input_fn = input_fn or input
    external_runner = external_runner or runner.run_external
    try:
        saved_config = load()
    except (ValueError, OSError) as exc:
        print(f"個人設定を確認してください: {exc}", file=sys.stderr)
        return 2
    print("新しい問題を作成します。/back で前へ、/cancel または Ctrl-C で中止できます。")
    case = None
    run_root = None
    run_started = False
    try:
        while True:
            try:
                category = _choose(input_fn, "カテゴリを選択:", tuple((name, name) for name in CATEGORIES))
                name = _problem_name(input_fn)
                break
            except Back:
                print("カテゴリ選択に戻ります。")
        case_id = _new_case_id(root, category, name)
        case = root / "categories" / category / "cases" / case_id
        try:
            case = runner.init_case(category, case_id, "Draft case; not authorized to run", 15,
                                    None, title=name, draft=True)
            files_dir = case / "input" / "files"
            files_dir.mkdir()
        except (ValueError, OSError):
            if case.exists():
                print(f"ケース作成が完了していない可能性があります: {case}", file=sys.stderr)
            raise
        print(f"ケースを作成しました: ID={case_id}\n場所: {case}")
        data = {"category": category, "name": name, "case_id": case_id}
        statement_path = case / "input" / "statement.txt"
        steps = ("files", "statement", "mode", "target", "minutes", "preset", "network", "confirm")
        step = 0
        while step < len(steps):
            try:
                current = steps[step]
                if current == "files":
                    data["files"] = _confirm_files(input_fn, files_dir)
                elif current == "statement":
                    statement = _statement(input_fn)
                    data["statement_hash"] = _write_statement(
                        statement_path, statement, data.get("statement_hash"))
                elif current == "mode":
                    data["mode"] = _choose(input_fn, "接続先の種類:",
                        (("offline", "ローカル問題（接続先なし）"), ("live", "許可されたライブ接続先あり")))
                elif current == "target":
                    data["target"] = _target(input_fn) if data["mode"] == "live" else None
                elif current == "minutes":
                    data["minutes"] = _minutes(input_fn)
                elif current == "preset":
                    data["preset"] = _choose(input_fn, "実行プリセット:",
                        (("test", "test: 類似検索 off、正解参照 off"),
                         ("production", "production: 類似検索 on、正解参照 off")))
                elif current == "network":
                    data["network"] = "off" if data["target"] is None else saved_config["network_access"]
                    if data["target"] is None and saved_config["network_access"] == "on":
                        print("接続先なしを選択したため、この実行だけネットワークを off にします。")
                    if data["target"] is not None and data["network"] == "off":
                        print("個人設定のネットワークは off です。ライブ接続先にはこのまま接続できません。")
                        while True:
                            answer = _read(input_fn, "この実行だけ有効にするなら ENABLE（戻るなら /back）: ").strip()
                            if answer == "ENABLE":
                                data["network"] = "on"
                                break
                            print("明示的な ENABLE が必要です。")
                else:
                    data["scope_note"] = (f"Authorized CTF endpoint {data['target']} only" if data["target"]
                                          else "Local challenge input only; no live target")
                    run_config = {**saved_config, "network_access": data["network"]}
                    switches = runner.choose_switches(data["preset"], "auto", "off")
                    _summarize(case, data, run_config, switches)
                    if not ask("封印して実行しますか", yes=auto_yes,
                               input_fn=lambda prompt: _read(input_fn, prompt), tty=tty):
                        raise Cancelled
                step += 1
            except Back:
                if step == 0:
                    print("ケースのカテゴリと名前は確定済みです。中止するなら /cancel。")
                else:
                    step -= 1
                    print("前の項目に戻ります。")
            except ValueError as exc:
                print(f"入力を確認してください: {exc}")
        if _scan_files(files_dir) != data["files"] or sha256(statement_path) != data["statement_hash"]:
            raise ValueError("確認後に入力ファイルが変わりました。下書きを残し、実行は中止しました")
        with category_lock(category, root):
            runner.finalize_case(category, case_id, data["scope_note"], data["minutes"], data["target"])
            runner.seal_case(category, case_id)
            run_started = True
            if run_config["orchestration"] == "interactive":
                if interactive_runner is None:
                    raise ValueError("interactive runner is unavailable")
                run_root = interactive_runner(category, case_id, run_config, switches, None, None)
            else:
                run_root = external_runner(category, case_id, run_config, switches, None, None,
                                           progress=run_config["progress"], owner_confirmation=True)
        result_path = run_root / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            print(f"実行結果: {result['status']} / {result_path}")
            candidate = run_root / "candidate.txt"
            if candidate.is_file():
                print("候補: " + json.dumps(candidate.read_text(encoding="utf-8").rstrip("\n"), ensure_ascii=True))
            else:
                print(f"集約候補なし。各役割の結果は {run_root} に保存されています。")
        else:
            print(f"対話セッション: {run_root}")
        return 0
    except (Cancelled, ConfirmationCancelled):
        if case is None or not case.is_dir():
            print("中止しました。ケースは作成されていません。")
        else:
            print(f"中止しました。下書きは {case} に残っています。seal/run はしていません。")
        return 0
    except KeyboardInterrupt:
        print("実行が中断されました。既存の記録を確認してください。", file=sys.stderr)
        return 130
    except (ValueError, OSError) as exc:
        print(f"中止: {exc}", file=sys.stderr)
        if case is not None and case.is_dir():
            print(f"ケースの場所: {case}。状態を確認してから再利用してください。", file=sys.stderr)
        return 2
    finally:
        if run_started and case is not None:
            if run_root is None:
                runs = root / "categories" / category / "runs" / case_id
                existing = sorted(path for path in runs.iterdir() if path.is_dir()) if runs.is_dir() else []
                if len(existing) == 1:
                    run_root = existing[0]
            if run_root is not None:
                owner_record = run_root / "OWNER_CONFIRMATION.json"
                if owner_record.is_file():
                    print(f"正解報告：{owner_record}")
                solution = run_root / "SOLUTION.md"
                if solution.is_file():
                    print(f"解法ファイル：{solution}")
                handoff = run_root / "HANDOFF.md"
                if handoff.is_file():
                    print(f"引継ぎファイル：{handoff}")
                print(f"ログ保存先：{run_root}")

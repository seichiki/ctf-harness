"""Reversible, locked archive moves for case inputs and run histories."""

from __future__ import annotations

import json
import os
import re
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from harness.config import CATEGORIES, ROOT
from harness.locks import category_lock

ARCHIVE_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}\Z")
KINDS = ("cases", "runs")


def _archive_root(root: Path, create: bool = False) -> Path:
    path = root / "archives"
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError("archives path must be a real directory")
    if create:
        path.mkdir(exist_ok=True)
    return path


def _safe_tree(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"expected a real directory: {path}")
    for current, directories, files in os.walk(path, followlinks=False):
        if any((Path(current) / name).is_symlink() for name in (*directories, *files)):
            raise ValueError(f"symlinks are not allowed in archive data: {path}")


def _items(root: Path, selected: tuple[str, ...]) -> list[dict[str, str]]:
    items = []
    for category in selected:
        for kind in KINDS:
            source = root / "categories" / category / kind
            if not source.exists() and not source.is_symlink():
                continue
            _safe_tree(source)
            if any(source.iterdir()):
                items.append({"category": category, "kind": kind,
                              "original": f"categories/{category}/{kind}",
                              "archived": f"{category}/{kind}"})
    return items


def _write_manifest(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _remove_empty_staging(stage: Path, items: list[dict[str, str]]) -> None:
    manifest = stage / "manifest.json"
    if manifest.is_file() and not manifest.is_symlink():
        manifest.unlink()
    for category in sorted({item["category"] for item in items}):
        directory = stage / category
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    if stage.is_dir() and not any(stage.iterdir()):
        stage.rmdir()


def archive_categories(root: Path = ROOT, categories: tuple[str, ...] = (),
                       *, confirm: bool = False) -> dict:
    selected = tuple(sorted(set(categories)))
    if not selected or any(category not in CATEGORIES for category in selected):
        raise ValueError("select a valid category or explicitly select all categories")
    with ExitStack() as locks:
        for category in selected:
            locks.enter_context(category_lock(category, root, exclusive=True))
        archive_root = _archive_root(root)
        items = _items(root, selected)
        plan = {"action": "archive", "selected_categories": list(selected),
                "archive_root": str(archive_root), "items": items,
                "status": "ready" if items else "nothing_to_archive"}
        if not confirm or not items:
            return plan
        archive_root = _archive_root(root, create=True)
        archive_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        stage = archive_root / f".pending-{archive_id}"
        final = archive_root / archive_id
        if stage.exists() or final.exists() or stage.is_symlink() or final.is_symlink():
            raise ValueError("archive ID collision; no data moved")
        manifest = {"archive_id": archive_id, "created_at": datetime.now(timezone.utc).isoformat(),
                    "status": "prepared", "selected_categories": list(selected), "items": items}
        stage.mkdir()
        moved: list[tuple[Path, Path]] = []
        try:
            _write_manifest(stage / "manifest.json", manifest)
            for item in items:
                source = root / item["original"]
                destination = stage / item["archived"]
                destination.parent.mkdir(exist_ok=True)
                source.rename(destination)
                moved.append((source, destination))
                source.mkdir()
            manifest["status"] = "complete"
            _write_manifest(stage / "manifest.json", manifest)
            stage.rename(final)
        except Exception as exc:
            recovery_errors = []
            for source, destination in reversed(moved):
                try:
                    if source.exists():
                        if source.is_symlink() or not source.is_dir() or any(source.iterdir()):
                            raise ValueError("new data appeared at original location")
                        source.rmdir()
                    destination.rename(source)
                except Exception as rollback_error:
                    recovery_errors.append(type(rollback_error).__name__)
            if recovery_errors:
                manifest["status"] = "recovery_needed"
                _write_manifest(stage / "manifest.json", manifest)
                raise ValueError(f"archive recovery needed at {stage}; no data was purged") from exc
            _remove_empty_staging(stage, items)
            raise ValueError("archive failed; original case and run directories were restored") from exc
        return {**plan, "status": "archived", "archive_id": archive_id,
                "archive_dir": str(final), "manifest": str(final / "manifest.json")}


def _load_archive(root: Path, archive_id: str) -> tuple[Path, dict]:
    if not ARCHIVE_ID.fullmatch(archive_id):
        raise ValueError("invalid archive ID")
    directory = _archive_root(root) / archive_id
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("archive is missing or is a symlink")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("archive manifest is missing or a symlink")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("archive manifest must be an object")
    if data.get("archive_id") != archive_id or data.get("status") not in ("complete", "restored"):
        raise ValueError("archive is incomplete or has an invalid manifest")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("archive has no valid items")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid archive item")
        category, kind = item.get("category"), item.get("kind")
        if (not isinstance(category, str) or not isinstance(kind, str) or
                category not in CATEGORIES or kind not in KINDS or (category, kind) in seen or
                item.get("original") != f"categories/{category}/{kind}" or
                item.get("archived") != f"{category}/{kind}"):
            raise ValueError("archive item path is invalid")
        seen.add((category, kind))
        if data["status"] == "complete":
            _safe_tree(directory / item["archived"])
    return directory, data


def restore_archive(root: Path = ROOT, archive_id: str = "", *, confirm: bool = False) -> dict:
    directory, data = _load_archive(root, archive_id)
    selected = tuple(sorted({item["category"] for item in data["items"]}))
    with ExitStack() as locks:
        for category in selected:
            locks.enter_context(category_lock(category, root, exclusive=True))
        # Re-check after taking locks, since another restore may have completed.
        directory, data = _load_archive(root, archive_id)
        conflicts = []
        for item in data["items"]:
            target = root / item["original"]
            if target.is_symlink() or (target.exists() and
                                      (not target.is_dir() or any(target.iterdir()))):
                conflicts.append(item["original"])
        plan = {"action": "restore", "archive_id": archive_id, "archive_dir": str(directory),
                "items": data["items"], "conflicts": conflicts,
                "status": "already_restored" if data["status"] == "restored" else
                          "conflict" if conflicts else "ready"}
        if not confirm:
            return plan
        if plan["status"] != "ready":
            raise ValueError("restore refused: archive already restored or active case/run data conflicts")
        moved: list[tuple[Path, Path]] = []
        removed_empty: list[Path] = []
        manifest_path = directory / "manifest.json"
        try:
            data["status"] = "restoring"
            _write_manifest(manifest_path, data)
            for item in data["items"]:
                source = directory / item["archived"]
                target = root / item["original"]
                if target.exists():
                    target.rmdir()
                    removed_empty.append(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
                moved.append((source, target))
            data["status"] = "restored"
            data["restored_at"] = datetime.now(timezone.utc).isoformat()
            _write_manifest(manifest_path, data)
        except Exception as exc:
            recovery_errors = []
            for source, target in reversed(moved):
                try:
                    source.parent.mkdir(exist_ok=True)
                    target.rename(source)
                    target.mkdir()
                except Exception as rollback_error:
                    recovery_errors.append(type(rollback_error).__name__)
            for target in removed_empty:
                if not target.exists():
                    try:
                        target.mkdir()
                    except Exception as rollback_error:
                        recovery_errors.append(type(rollback_error).__name__)
            data["status"] = "recovery_needed" if recovery_errors else "complete"
            _write_manifest(manifest_path, data)
            if recovery_errors:
                raise ValueError(f"restore recovery needed at {directory}; no data was purged") from exc
            raise ValueError("restore failed; archive contents were returned to the archive") from exc
        return {**plan, "status": "restored", "manifest": str(manifest_path)}


def list_archives(root: Path = ROOT) -> list[dict[str, str]]:
    archive_root = _archive_root(root)
    if not archive_root.exists():
        return []
    result = []
    for path in sorted(archive_root.iterdir()):
        if path.is_symlink() or not path.is_dir():
            continue
        manifest = path / "manifest.json"
        status = "incomplete"
        if manifest.is_file() and not manifest.is_symlink():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                candidate = data.get("status") if isinstance(data, dict) else None
                if candidate in ("prepared", "complete", "restoring", "restored", "recovery_needed"):
                    status = candidate
            except (OSError, json.JSONDecodeError):
                pass
        result.append({"archive_id": path.name, "status": status, "path": str(path)})
    return result

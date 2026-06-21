"""Project Workspace MVP helpers.

Lightweight workspace switching is intentionally host-side state: the active
workspace is a resolved cwd bound to a Hermes session/chat, while
``terminal.cwd`` remains the fallback infrastructure cwd.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from hermes_constants import get_hermes_home
from utils import atomic_replace


SUPPORTED_CONTEXT_FILES = ("AGENTS.md", ".hermes.md", "HERMES.md", "CLAUDE.md", ".cursorrules")


@dataclass(frozen=True)
class WorkspaceOutcome:
    handled: bool
    message: str = ""
    cwd: str = ""
    name: str = ""
    context_file: str = ""
    persistent: bool = False


def projects_path() -> Path:
    return get_hermes_home() / "projects.yaml"


def load_projects(path: Path | None = None) -> dict[str, Any]:
    p = path or projects_path()
    if not p.exists():
        return {"version": 1, "workspaces": {}, "bindings": {"sessions": {}, "chats": {}}}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("workspaces", {})
    data.setdefault("bindings", {})
    if not isinstance(data["workspaces"], dict):
        data["workspaces"] = {}
    if not isinstance(data["bindings"], dict):
        data["bindings"] = {}
    data["bindings"].setdefault("sessions", {})
    data["bindings"].setdefault("chats", {})
    return data


def save_projects(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or projects_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        atomic_replace(tmp_path, p)
    finally:
        tmp_path.unlink(missing_ok=True)


def chat_binding_key(platform: str | None, chat_id: str | None, thread_id: str | None = None) -> str:
    if not platform or not chat_id:
        return ""
    return f"{platform}:{chat_id}:{thread_id or ''}"


def detect_context_file(cwd: str | Path) -> str:
    root = Path(cwd)
    for name in SUPPORTED_CONTEXT_FILES:
        if (root / name).is_file():
            return name
    return ""


def resolve_bound_cwd(
    *,
    session_id: str | None = None,
    platform: str | None = None,
    chat_id: str | None = None,
    thread_id: str | None = None,
    path: Path | None = None,
) -> str:
    data = load_projects(path)
    sessions = data.get("bindings", {}).get("sessions", {})
    if session_id and isinstance(sessions, dict):
        cwd = (sessions.get(str(session_id)) or {}).get("cwd")
        if cwd and Path(str(cwd)).is_dir():
            return str(cwd)
    key = chat_binding_key(platform, chat_id, thread_id)
    chats = data.get("bindings", {}).get("chats", {})
    if key and isinstance(chats, dict):
        cwd = (chats.get(key) or {}).get("cwd")
        if cwd and Path(str(cwd)).is_dir():
            return str(cwd)
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _real_dir(path_text: str, *, must_exist: bool) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(path_text)))
    if not expanded.is_absolute():
        raise ValueError("workspace path must be absolute")
    if must_exist:
        return expanded.resolve(strict=True)
    return expanded


def _minimal_agents_md(name: str) -> str:
    display = name.strip() or "Workspace"
    return (
        "---\n"
        f"project_name: {display}\n"
        "---\n\n"
        "# AGENTS.md\n\n"
        "This file contains project-specific instructions for this workspace.\n\n"
        "## Project\n\n"
        f"Name: {display}\n\n"
        "## Build and test\n\n"
        "- Add build commands here.\n"
        "- Add test commands here.\n\n"
        "## Conventions\n\n"
        "- Add coding conventions here.\n"
    )


def _template_agents_md(name: str) -> str:
    template = get_hermes_home() / "templates" / "AGENTS.md"
    if template.is_file():
        try:
            return template.read_text(encoding="utf-8")
        except Exception:
            pass
    return _minimal_agents_md(name)


_CD_RE = re.compile(r"^\s*cd\s+(?P<path>(?:\"[^\"]+\"|'[^']+'|\S+))(?:\s+#(?P<name>[A-Za-z0-9_. -]+))?\s*$")
_SWITCH_EN_RE = re.compile(r"^\s*switch\s+to\s+(?P<name>.+?)\s+project\s*$", re.IGNORECASE)
_SWITCH_ZH_RE = re.compile(r"^\s*切换到\s*(?P<name>.+?)\s*项目\s*$")


def _unquote_path(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    return raw.replace("\\ ", " ")


def _workspace_display_name(data: dict[str, Any], cwd: str, explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    saved = (data.get("workspaces", {}).get(cwd) or {}).get("name")
    if saved:
        return str(saved)
    return Path(cwd).name or cwd


def bind_workspace(
    cwd: str,
    *,
    name: str = "",
    context_file: str = "",
    session_id: str | None = None,
    platform: str | None = None,
    chat_id: str | None = None,
    thread_id: str | None = None,
    path: Path | None = None,
) -> tuple[str, str]:
    resolved = str(Path(cwd).resolve(strict=True))
    data = load_projects(path)
    now = _now()
    workspaces = data.setdefault("workspaces", {})
    existing = workspaces.get(resolved) if isinstance(workspaces.get(resolved), dict) else {}
    display = _workspace_display_name(data, resolved, name)
    workspaces[resolved] = {
        "name": display,
        "context_file": context_file or existing.get("context_file") or detect_context_file(resolved),
        "first_seen_at": existing.get("first_seen_at") or now,
        "last_used_at": now,
    }
    bindings = data.setdefault("bindings", {})
    if session_id:
        bindings.setdefault("sessions", {})[str(session_id)] = {"cwd": resolved, "updated_at": now}
    key = chat_binding_key(platform, chat_id, thread_id)
    if key:
        bindings.setdefault("chats", {})[key] = {"cwd": resolved, "updated_at": now}
    save_projects(data, path)
    return resolved, display


def find_by_name(name: str, *, path: Path | None = None) -> list[tuple[str, dict[str, Any]]]:
    needle = name.strip().casefold()
    if not needle:
        return []
    data = load_projects(path)
    matches = []
    for cwd, meta in data.get("workspaces", {}).items():
        if isinstance(meta, dict) and str(meta.get("name") or "").casefold() == needle:
            matches.append((str(cwd), meta))
    return matches


def handle_workspace_message(
    message: str,
    *,
    session_id: str | None = None,
    platform: str | None = None,
    chat_id: str | None = None,
    thread_id: str | None = None,
    path: Path | None = None,
) -> WorkspaceOutcome:
    text = str(message or "").strip()
    if not text:
        return WorkspaceOutcome(False)

    m = _CD_RE.match(text)
    if m:
        raw_path = _unquote_path(m.group("path"))
        explicit_name = (m.group("name") or "").strip()
        try:
            if explicit_name:
                cwd_path = _real_dir(raw_path, must_exist=False)
                created_dir = False
                if not cwd_path.exists():
                    cwd_path.mkdir(parents=True)
                    created_dir = True
                if not cwd_path.is_dir():
                    return WorkspaceOutcome(True, f"Workspace path is not a directory: {cwd_path}")
                cwd = str(cwd_path.resolve(strict=True))
                context = detect_context_file(cwd)
                created_context = False
                if not context:
                    agents = Path(cwd) / "AGENTS.md"
                    agents.write_text(_template_agents_md(explicit_name), encoding="utf-8")
                    context = "AGENTS.md"
                    created_context = True
                cwd, display = bind_workspace(
                    cwd,
                    name=explicit_name,
                    context_file=context,
                    session_id=session_id,
                    platform=platform,
                    chat_id=chat_id,
                    thread_id=thread_id,
                    path=path,
                )
                if created_dir or created_context:
                    return WorkspaceOutcome(
                        True,
                        f"Workspace initialized.\nName: {display}\nPath: {cwd}\nContext: {context} created and loaded",
                        cwd,
                        display,
                        context,
                        True,
                    )
                return WorkspaceOutcome(
                    True,
                    f"Workspace switched.\nName: {display}\nPath: {cwd}\nContext: {context} loaded",
                    cwd,
                    display,
                    context,
                    True,
                )

            cwd_path = _real_dir(raw_path, must_exist=True)
            if not cwd_path.is_dir():
                return WorkspaceOutcome(True, f"Workspace path is not a directory: {cwd_path}")
            cwd = str(cwd_path.resolve(strict=True))
        except FileNotFoundError:
            return WorkspaceOutcome(
                True,
                f"Directory not found: {raw_path}\nTo initialize a new workspace, use:\ncd {raw_path} #ProjectName",
            )
        except ValueError as exc:
            return WorkspaceOutcome(True, str(exc))
        except OSError as exc:
            return WorkspaceOutcome(True, f"Could not open workspace path: {exc}")

        context = detect_context_file(cwd)
        if not context:
            return WorkspaceOutcome(
                True,
                f"Directory changed.\nPath: {cwd}\nContext: no project context found\nPersistent workspace binding: not updated",
                cwd,
                Path(cwd).name,
                "",
                False,
            )
        cwd, display = bind_workspace(
            cwd,
            context_file=context,
            session_id=session_id,
            platform=platform,
            chat_id=chat_id,
            thread_id=thread_id,
            path=path,
        )
        return WorkspaceOutcome(
            True,
            f"Workspace switched.\nName: {display}\nPath: {cwd}\nContext: {context} loaded",
            cwd,
            display,
            context,
            True,
        )

    m = _SWITCH_EN_RE.match(text) or _SWITCH_ZH_RE.match(text)
    if not m:
        return WorkspaceOutcome(False)
    name = m.group("name").strip()
    matches = find_by_name(name, path=path)
    matches = [(cwd, meta) for cwd, meta in matches if Path(cwd).is_dir()]
    if not matches:
        return WorkspaceOutcome(
            True,
            f"No workspace named {name} was found.\nCreate or register it with:\ncd /absolute/path/to/new-app #{name}",
        )
    if len(matches) > 1:
        paths = "\n".join(f"- {cwd}" for cwd, _ in matches)
        return WorkspaceOutcome(True, f"Multiple workspaces named {name} were found. Specify the path:\n{paths}")
    cwd, meta = matches[0]
    context = detect_context_file(cwd) or str(meta.get("context_file") or "")
    cwd, display = bind_workspace(
        cwd,
        name=name,
        context_file=context,
        session_id=session_id,
        platform=platform,
        chat_id=chat_id,
        thread_id=thread_id,
        path=path,
    )
    return WorkspaceOutcome(
        True,
        f"Workspace switched.\nName: {display}\nPath: {cwd}\nContext: {context or 'no project context found'} loaded",
        cwd,
        display,
        context,
        True,
    )

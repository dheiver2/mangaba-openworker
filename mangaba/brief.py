"""Long-horizon session continuity: a per-workspace "living brief" + auto session summaries.

Sessions are isolated; a flat memory store can't represent "where this project stands".
This module gives each workspace a **living brief** (objective, decisions, open threads, last
session summary) that the agent reads at session start (via context injector) and can update
via `brief_write`. At session end the agent is nudged to summarize via `brief_close`, and a
mechanical fallback (`summarize_session`) extracts the last assistant text when the model
didn't write one — so interrupting a session never loses the thread.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import aisuite as ai


@dataclass
class SessionBrief:
    objective: str = ""
    decisions: list[str] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    last_summary: str = ""
    updated_at: float = field(default_factory=time.time)


class BriefStore:
    """A JSON file per workspace under the state dir; lock-guarded for the threaded server."""

    def __init__(self, state_path: str | Path) -> None:
        self._root = Path(state_path)
        self._root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, SessionBrief] = {}
        self._lock = threading.Lock()

    def _path(self, workspace: str) -> Path:
        safe = _safe_key(workspace)
        return self._root / f"{safe}.json"

    def get(self, workspace: str) -> SessionBrief:
        with self._lock:
            if workspace in self._cache:
                return self._cache[workspace]
            brief = SessionBrief()
            path = self._path(workspace)
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    brief = SessionBrief(**{k: v for k, v in data.items() if k in SessionBrief.__dataclass_fields__})
                except (json.JSONDecodeError, TypeError):
                    brief = SessionBrief()
            self._cache[workspace] = brief
            return brief

    def update(self, workspace: str, **changes: Any) -> SessionBrief:
        brief = self.get(workspace)
        for key, value in changes.items():
            if key in SessionBrief.__dataclass_fields__:
                setattr(brief, key, value)
        brief.updated_at = time.time()
        with self._lock:
            self._path(workspace).write_text(
                json.dumps(asdict(brief), ensure_ascii=False), encoding="utf-8"
            )
            self._cache[workspace] = brief
        return brief


def _safe_key(workspace: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in (workspace or "root"))[:80] or "root"


def brief_block(brief: SessionBrief) -> str:
    """Render the living brief as a `<project-brief>` block for the context injector."""
    lines = [
        "Project brief (from earlier sessions):",
        f"- Objective: {brief.objective or '(none set)'}",
    ]
    if brief.decisions:
        lines.append("- Decisions: " + " · ".join(brief.decisions[-5:]))
    if brief.open_threads:
        lines.append("- Open threads: " + " · ".join(brief.open_threads[-5:]))
    if brief.last_summary:
        lines.append(f"- Last session: {brief.last_summary[:400]}")
    return "\n".join(lines)


def summarize_session(messages: list[dict]) -> str:
    """Mechanical fallback summary: the latest assistant TEXT after the last tool batch.
    Not a replacement for a model-written summary — just enough continuity to resume."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant" or msg.get("tool_calls"):
            continue
        content = msg.get("content")
        text = "".join(p.get("text", "") for p in content if isinstance(p, dict)) if isinstance(content, list) else str(content or "")
        text = text.strip()
        if text:
            return text[:600]
    return ""


def brief_tools(store: BriefStore, workspace: str) -> list:
    def brief_get() -> dict[str, Any]:
        """Read the current project brief (objective, decisions, open threads, last summary)."""
        b = store.get(workspace)
        return {
            "objective": b.objective,
            "decisions": b.decisions,
            "open_threads": b.open_threads,
            "last_summary": b.last_summary,
        }

    def brief_write(
        objective: str = "",
        decisions: Optional[list[str]] = None,
        open_threads: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Update the project brief — set the objective, append decisions and open_threads.
        Call at session start to confirm the objective and at the end to record wrap-up."""
        changes: dict[str, Any] = {}
        if objective:
            changes["objective"] = objective
        if decisions:
            b = store.get(workspace)
            b.decisions = (b.decisions + [d for d in decisions if d not in b.decisions])[-20:]
            changes["decisions"] = b.decisions
        if open_threads:
            b = store.get(workspace)
            b.open_threads = open_threads
            changes["open_threads"] = b.open_threads
        store.update(workspace, **changes)
        return {"ok": True, "brief": brief_get()}

    def brief_end(summary: str) -> dict[str, Any]:
        """Record this session's summary into the project brief so the next session can
        resume seamlessly. Call once at the end of a working session."""
        store.update(workspace, last_summary=(summary or "").strip())
        return {"ok": True}

    def _wrap(fn, name, doc):
        fn.__name__ = name
        fn.__doc__ = doc
        return ai.tool(
            fn,
            metadata=ai.ToolMetadata(
                name=name,
                category="memory",
                risk_level="low",
                capabilities=["brief"],
                requires_approval=False,
            ),
        )

    return [
        _wrap(brief_get, "brief_get", brief_get.__doc__),
        _wrap(brief_write, "brief_write", brief_write.__doc__),
        _wrap(brief_end, "brief_end", brief_end.__doc__),
    ]
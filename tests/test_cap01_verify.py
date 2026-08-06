"""Capability #1 — structured verification (run_verify + tracker + done-gate nudge)."""

from __future__ import annotations

from mangaba.tools import ToolRegistry
from mangaba.tools.shell import LocalExecutor
from mangaba.tools.verify import (
    VerifyTracker,
    verification_nudge_text,
    verify_tools,
)


class _FakeExecutor:
    """An executor that returns a scripted exit code (no real shell)."""

    def __init__(self, codes):
        self.codes = list(codes)
        self.calls = []

    def run(self, command, timeout=None):
        self.calls.append(command)
        code = self.codes.pop(0) if self.codes else 0
        return {"exit_code": code, "output": f"ran {command}"}


def test_run_verify_reports_pass_and_failure(tmp_path):
    ex = _FakeExecutor([0, 1])
    reg = ToolRegistry()
    reg.register_all(verify_tools(ex))
    ok = reg.execute("run_verify", {"command": "pytest -q"})
    assert ok["passed"] is True and ok["exit_code"] == 0
    bad = reg.execute("run_verify", {"command": "pytest -q"})
    assert bad["passed"] is False and bad["consecutive_failures"] == 1


def test_verify_history(tmp_path):
    ex = _FakeExecutor([1, 1, 0])
    reg = ToolRegistry()
    reg.register_all(verify_tools(ex))
    reg.execute("run_verify", {"command": "a"})
    reg.execute("run_verify", {"command": "a"})
    reg.execute("run_verify", {"command": "a"})
    hist = reg.execute("verify_history", {})
    assert hist["total_runs"] == 3 and hist["passed"] == 1 and hist["failed"] == 2


def test_consecutive_failures_reset_on_success():
    tracker = VerifyTracker()
    tracker.record("pytest", 1)
    tracker.record("pytest", 1)
    assert tracker.consecutive_failures() == 2
    tracker.record("pytest", 0)
    assert tracker.consecutive_failures() == 0


def test_tracker_resets_streak_on_new_command():
    tracker = VerifyTracker()
    tracker.record("pytest", 1)
    tracker.record("lint", 1)
    # streak is per-target: the later "lint" failure resets the "pytest" streak
    assert tracker.consecutive_failures("lint") == 1
    assert tracker.consecutive_failures("pytest") == 0


def test_nudge_fires_after_threshold():
    tracker = VerifyTracker()
    tracker.record("pytest -q", 1)
    assert verification_nudge_text(tracker, threshold=2) is None
    tracker.record("pytest -q", 1)
    text = verification_nudge_text(tracker, threshold=2)
    assert text is not None and "run_verify" in text


def test_nudge_silent_when_passing():
    tracker = VerifyTracker()
    tracker.record("pytest -q", 0)
    assert verification_nudge_text(tracker, threshold=2) is None
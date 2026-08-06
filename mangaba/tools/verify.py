"""Structured self-verification — `run_verify` + a per-session failure tracker.

The Code agent's prompt already says "verifique"; this turns that instruction into a
first-class capability. `run_verify` runs a verification command (test/lint/build/typecheck)
through the session's executor and returns a STRUCTURED verdict — exit code, tail of output,
and whether the failure is fresh. The engine reads the tracker after each tool batch
(`_maybe_nudge_verification`) and, when the SAME verify target fails twice in a row, injects
a steering message ("fix it and re-run") — the verify → fix → retest loop, bounded and
non-loopy because the nudge fires once per run of consecutive failures and the model does
the actual fixing between calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aisuite as ai

from .shell import Executor

_MAX_VERIFY_OUTPUT = 4000


@dataclass
class VerifyRun:
    command: str
    exit_code: int
    started_at: float
    succeeded: bool = False
    """True when the tracker marks this run as superseded by a passing one."""


@dataclass
class VerifyTracker:
    """Session-scoped record of verification runs. The engine consults `consecutive_failures`
    to decide whether to nudge the model into fixing + re-running."""

    runs: list[VerifyRun] = field(default_factory=list)
    _last_signature: Optional[str] = None

    def record(self, command: str, exit_code: int) -> None:
        self.runs.append(VerifyRun(command=command, exit_code=exit_code, started_at=time.time()))
        # A passing run resets the streak; a failing run under a NEW command also resets it
        # (the streak is per-target, not global).
        if exit_code == 0:
            self._last_signature = None
        else:
            self._last_signature = command

    def consecutive_failures(self, command: Optional[str] = None) -> int:
        """How many consecutive failing runs ended on `command` (or the current target)."""
        count = 0
        for run in reversed(self.runs):
            if run.exit_code == 0:
                break
            if command is not None and run.command != command:
                break
            count += 1
        return count

    def last(self) -> Optional[VerifyRun]:
        return self.runs[-1] if self.runs else None


def verify_tools(executor: Optional[Executor], tracker: Optional[VerifyTracker] = None) -> list:
    """`run_verify` + `verify_history`. Without an executor, `run_verify` reports it can't run
    (some surfaces have no shell) and `verify_history` still reflects the tracker."""
    tracker = tracker or VerifyTracker()

    def run_verify(
        command: str,
        description: str = "",
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        """Run a verification command (test / lint / build / typecheck) and return a structured
        verdict: exit code, the tail of the output, and whether the repo was already clean for
        this command. Use this after changes instead of ad-hoc `run_shell` for checks — the
        runtime tracks failures and will nudge you to fix + re-run. A passing run resets the
        failure streak.

        Args:
            command (str): The verification command to run.
            description (str): Short human note shown in approval prompts.
            timeout_seconds (int): Max seconds before the command is killed.
        """
        if executor is None:
            return {"error": "no shell executor in this session"}
        timeout = min(max(1, int(timeout_seconds)), 600)
        result = executor.run(command, timeout=float(timeout))
        exit_code = result.get("exit_code")
        if exit_code is None:
            exit_code = result.get("code")
        exit_code = int(exit_code) if exit_code is not None else 1
        output = str(result.get("output") or "")
        tracker.record(command, exit_code)
        passed = exit_code == 0
        tail = output[-_MAX_VERIFY_OUTPUT:] if output else ""
        return {
            "command": command,
            "passed": passed,
            "exit_code": exit_code,
            "output_tail": tail,
            "consecutive_failures": (
                0 if passed else tracker.consecutive_failures(command)
            ),
        }

    def verify_history() -> dict[str, Any]:
        """Summarize the verification runs so far this session: passing/failing counts and the
        current target's streak. Lets the model report honestly when something stays red."""
        runs = tracker.runs
        return {
            "total_runs": len(runs),
            "passed": sum(1 for r in runs if r.exit_code == 0),
            "failed": sum(1 for r in runs if r.exit_code != 0),
            "current_failing": (
                tracker.last().command
                if tracker.last() and tracker.last().exit_code != 0
                else None
            ),
        }

    def _wrap(fn, name, doc, schema=None):
        fn.__name__ = name
        fn.__doc__ = doc
        wrapped = ai.tool(
            fn,
            metadata=ai.ToolMetadata(
                name=name,
                category="verification",
                risk_level="low",
                capabilities=["verify"],
                requires_approval=False,
            ),
        )
        if schema is not None:
            wrapped.__mangaba_schema__ = schema
        return wrapped

    return [
        _wrap(
            run_verify,
            "run_verify",
            run_verify.__doc__,
            {
                "type": "function",
                "function": {
                    "name": "run_verify",
                    "description": run_verify.__doc__,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "description": {"type": "string"},
                            "timeout_seconds": {"type": "integer"},
                        },
                        "required": ["command"],
                    },
                },
            },
        ),
        _wrap(verify_history, "verify_history", verify_history.__doc__),
    ]


def verification_nudge_text(tracker: VerifyTracker, threshold: int = 2) -> Optional[str]:
    """The steering text when the current verify target keeps failing at `threshold` runs.
    Returns None when there's nothing to nudge — cheap, side-effect free, callable from the
    engine loop."""
    if not tracker.runs:
        return None
    last = tracker.last()
    if last is None or last.exit_code == 0:
        return None
    if tracker.consecutive_failures() < threshold:
        return None
    return (
        "A verificação ainda falha após %d tentativas do mesmo comando "
        "(`%s`). Não declare pronto: corrija a causa real e re-execute `run_verify`. "
        "Se não conseguir destravar, exponha o impedimento no resumo final em vez de "
        "relatar como verificado."
        % (tracker.consecutive_failures(), last.command)
    )

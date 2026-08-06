"""Capability #4 — first-class Plan (steps + dependencies + done-gate)."""

from __future__ import annotations

from mangaba.plan import Plan, plan_nudge_text, plan_tools
from mangaba.tools import ToolRegistry


def test_plan_write_and_summary():
    plan = Plan()
    reg = ToolRegistry()
    reg.register_all(plan_tools(plan))
    res = reg.execute(
        "plan_write",
        {
            "steps": [
                {"id": "a", "description": "explorar", "status": "done"},
                {"id": "b", "description": "editar", "depends_on": ["a"], "status": "in_progress"},
                {"id": "c", "description": "testar", "depends_on": ["b"], "status": "pending"},
            ]
        },
    )
    assert res["open"] == 2 and res["blocked"] == 0
    assert res["steps"][1]["depends_on"] == ["a"]


def test_plan_dependency_blocks_progress():
    plan = Plan()
    reg = ToolRegistry()
    reg.register_all(plan_tools(plan))
    reg.execute(
        "plan_write",
        {
            "steps": [
                {"id": "a", "description": "base", "status": "pending"},
                {"id": "b", "description": "sobre", "depends_on": ["a"], "status": "pending"},
            ]
        },
    )
    # Can't mark 'b' in_progress while 'a' is pending.
    res = reg.execute("plan_step_status", {"step_id": "b", "status": "in_progress"})
    assert res["ok"] is False and "blocked" in res["error"]


def test_plan_done_gate_ignores_blocked_steps():
    plan = Plan()
    plan.replace(
        [
            {"id": "a", "description": "base", "status": "done"},
            {"id": "b", "description": "aguarda externo", "depends_on": ["a"], "status": "blocked"},
        ]
    )
    # b is open but blocked -> no nudge (it's expected to wait).
    assert plan_nudge_text(plan) is None


def test_plan_done_gate_nudges_unblocked_open():
    plan = Plan()
    plan.replace(
        [{"id": "a", "description": "entregar", "status": "pending"}]
    )
    text = plan_nudge_text(plan)
    assert text is not None and "passos abertos" in text


def test_plan_no_nudge_when_empty():
    assert plan_nudge_text(Plan()) is None


def test_plan_step_status_valid():
    plan = Plan()
    reg = ToolRegistry()
    reg.register_all(plan_tools(plan))
    reg.execute("plan_write", {"steps": [{"id": "x", "description": "t", "status": "pending"}]})
    assert reg.execute("plan_step_status", {"step_id": "x", "status": "done"})["ok"] is True
    assert reg.execute("plan_step_status", {"step_id": "nope", "status": "done"})["ok"] is False
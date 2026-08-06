"""Plan as a first-class object.

`todo_write` keeps a flat task list; a *plan* adds dependencies, per-step status, and
ownership tracking. The engine attaches a `Plan` to the session (`engine.plan`) and the
`plan_write` / `plan_step_status` tools maintain it. The engine's done-gate
(`_maybe_nudge_unfinished`) prefers the plan when present: a plan with open steps that
have no pending blockers is "done-shaped"; blocked steps (dependency unsatisfied) are
expected and don't trigger the nudge — that distinction is what makes a plan smarter than
a flat todo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import aisuite as ai

_PLAN_STATUSES = {"pending", "in_progress", "done", "blocked", "cancelled"}


@dataclass
class PlanStep:
    id: str
    description: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    note: str = ""

    def blockers(self, plan: "Plan") -> list[str]:
        return [
            d for d in self.depends_on
            if (step := plan.get(d)) is not None and step.status not in ("done", "cancelled")
        ]


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)

    def get(self, step_id: str) -> Optional[PlanStep]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def open_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status in ("pending", "in_progress")]

    def blocked_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status == "blocked"]

    def replace(self, raw: list[dict]) -> dict[str, Any]:
        """Replace the plan from `plan_write`'s argument shape, validating statuses/deps."""
        steps: list[PlanStep] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            sid = str(entry.get("id", "")).strip()
            if not sid:
                continue
            status = entry.get("status", "pending")
            if status not in _PLAN_STATUSES:
                status = "pending"
            steps.append(
                PlanStep(
                    id=sid,
                    description=str(entry.get("description", "")),
                    status=status,
                    depends_on=[
                        str(d) for d in entry.get("depends_on", []) if str(d).strip()
                    ],
                    note=str(entry.get("note", "")),
                )
            )
        known = {s.id for s in steps}
        for s in steps:
            s.depends_on = [d for d in s.depends_on if d in known]
        self.steps = steps
        return self.summary()

    def set_status(self, step_id: str, status: str) -> dict[str, Any]:
        step = self.get(step_id)
        if step is None:
            return {"ok": False, "error": f"no step with id {step_id}"}
        if status not in _PLAN_STATUSES:
            return {"ok": False, "error": f"invalid status {status!r}"}
        if status == "in_progress":
            blockers = step.blockers(self)
            if blockers:
                return {
                    "ok": False,
                    "error": f"step {step_id} blocked by: {', '.join(blockers)}",
                }
        step.status = status
        return {"ok": True, **self.summary()}

    def summary(self) -> dict[str, Any]:
        return {
            "open": len(self.open_steps()),
            "blocked": len(self.blocked_steps()),
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "status": s.status,
                    "depends_on": s.depends_on,
                }
                for s in self.steps
            ],
        }


# Explicit schema: the nested array-of-objects shape can't be auto-generated reliably.
_PLAN_SCHEMA = {
    "type": "function",
    "function": {
        "name": "plan_write",
        "description": (
            "Replace the execution plan. Each step has an id, description, optional "
            "depends_on (ids of steps that must finish first) and a status of pending, "
            "in_progress, done, blocked or cancelled. Provide the full plan each call. "
            "Track multi-step work here instead of todo_write — the runtime understands "
            "dependencies and only nudges you about steps that are actually unblocked."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "description": {"type": "string"},
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "done", "blocked", "cancelled"],
                            },
                        },
                        "required": ["id", "description", "status"],
                    },
                }
            },
            "required": ["steps"],
        },
    },
}

_STEP_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "plan_step_status",
        "description": "Update a single plan step's status (pending/in_progress/done/blocked/cancelled).",
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "blocked", "cancelled"],
                },
            },
            "required": ["step_id", "status"],
        },
    },
}


def plan_tools(plan: Plan) -> list:
    def plan_write(steps: list = None) -> dict:
        return plan.replace(steps or [])

    def plan_step_status(step_id: str, status: str) -> dict:
        return plan.set_status(step_id, status)

    def _wrap(fn, name, doc, schema):
        fn.__name__ = name
        fn.__doc__ = doc
        wrapped = ai.tool(
            fn,
            metadata=ai.ToolMetadata(
                name=name,
                category="planning",
                risk_level="low",
                capabilities=["plan"],
                requires_approval=False,
            ),
        )
        wrapped.__mangaba_schema__ = schema
        return wrapped

    return [
        _wrap(plan_write, "plan_write", _PLAN_SCHEMA["function"]["description"], _PLAN_SCHEMA),
        _wrap(
            plan_step_status,
            "plan_step_status",
            _STEP_STATUS_SCHEMA["function"]["description"],
            _STEP_STATUS_SCHEMA,
        ),
    ]


def plan_nudge_text(plan: Plan) -> str | None:
    """Done-gate for a plan: unblocked open steps that the model didn't close before ending."""
    if not plan.steps:
        return None
    open_steps = [s for s in plan.open_steps() if not s.blockers(plan)]
    if not open_steps:
        return None
    names = "; ".join(f"'{s.id}' ({s.description})" for s in open_steps[:4])
    return (
        "O plano ainda tem passos abertos e desbloqueados — "
        f"{names}. Conclua-os e atualize o status antes de encerrar; se um passo não "
        "se aplica mais, marque-o como cancelled/done e explique no resumo."
    )
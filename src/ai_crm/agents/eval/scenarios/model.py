from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "EVAL_AGENTS", "Expect", "HumanBaseline", "Op", "RESOURCE", "STRATEGIES", "Scenario",
    "delegate", "done", "propose",
]


STRATEGIES = ("single_agent", "multi_agent")


RESOURCE = [{"resource_type": "contact", "resource_id": "eval-contact-1"}]


@dataclass(frozen=True)
class Op:
    run: str
    key: str
    step_type: str
    input: dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    child: str | None = None
    tolerate: bool = False


@dataclass(frozen=True)
class Expect:
    proposals: int
    escalation: str | None = None


@dataclass(frozen=True)
class HumanBaseline:
    minutes: int
    interventions: int
    assumption: bool = True


@dataclass(frozen=True)
class Scenario:
    key: str
    description: str
    objective: str
    expect: Expect
    human: HumanBaseline
    single: tuple[Op, ...]
    multi: tuple[Op, ...]
    root_side_effects: int = 3

    def script(self, strategy: str) -> tuple[Op, ...]:
        return self.single if strategy == "single_agent" else self.multi


def propose(run: str, key: str, title: str, *, resource: bool = False) -> Op:
    body: dict[str, Any] = {"action_type": "task.create", "payload": {"title": title}}
    if resource:
        body["affected_resources"] = RESOURCE
    return Op(run, key, "propose", body, tokens=100)


def delegate(run: str, key: str, child: str, worker: str, objective: str, **extra: Any) -> Op:
    return Op(
        run,
        key,
        "delegate",
        {"worker": worker, "objective": objective, **extra},
        tokens=50,
        child=child,
    )


def done(run: str, key: str = "out") -> Op:
    return Op(run, key, "output", {"summary": "done"}, tokens=10)


EVAL_AGENTS: dict[str, dict[str, Any]] = {
    "lead": {
        "key": "eval-lead",
        "allowed_capabilities": ["read", "propose", "delegate", "escalate"],
        "max_depth": 1,
        "max_fanout": 3,
    },
    "worker_a": {
        "key": "eval-worker-a",
        "allowed_capabilities": ["read", "propose", "escalate"],
        "max_depth": 0,
        "max_fanout": 0,
    },
    "worker_b": {
        "key": "eval-worker-b",
        "allowed_capabilities": ["read", "propose", "escalate"],
        "max_depth": 0,
        "max_fanout": 0,
    },
}

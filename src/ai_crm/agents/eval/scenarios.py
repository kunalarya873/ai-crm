"""Replayable evaluation scenarios.

Scenarios are fixed, code-defined step scripts. They exercise the real coordination
services, so multi-agent vs single-agent figures are measured from persisted runs, but the
scripted behaviour is not a model, and the human baseline is a declared assumption.
"""

from dataclasses import dataclass, field
from typing import Any

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


SCENARIOS: dict[str, Scenario] = {
    scenario.key: scenario
    for scenario in (
        Scenario(
            key="parallel_research",
            description="Two independent follow-ups; no faults. Delegation is pure overhead here.",
            objective="Prepare renewal follow-ups",
            expect=Expect(proposals=2),
            human=HumanBaseline(minutes=40, interventions=3),
            single=(
                propose("root", "p1", "Follow up: pricing"),
                propose("root", "p2", "Follow up: contract"),
                done("root"),
            ),
            multi=(
                delegate("root", "d1", "a", "worker_a", "Pricing follow-up"),
                delegate("root", "d2", "b", "worker_b", "Contract follow-up"),
                propose("a", "p1", "Follow up: pricing"),
                done("a"),
                propose("b", "p1", "Follow up: contract"),
                done("b"),
                done("root"),
            ),
        ),
        Scenario(
            key="partial_failure",
            description="Part B hits a denied tool call; part A should still land.",
            objective="Handle two account tasks",
            expect=Expect(proposals=1, escalation="policy_denial"),
            human=HumanBaseline(minutes=35, interventions=2),
            single=(
                propose("root", "p1", "Part A"),
                Op(
                    "root",
                    "p2",
                    "propose",
                    {"action_type": "approval.request", "payload": {"title": "Part B"}},
                    tokens=100,
                ),
            ),
            multi=(
                delegate("root", "d1", "a", "worker_a", "Part A"),
                delegate("root", "d2", "b", "worker_b", "Part B"),
                propose("a", "p1", "Part A"),
                done("a"),
                Op(
                    "b",
                    "p1",
                    "propose",
                    {"action_type": "approval.request", "payload": {"title": "Part B"}},
                    tokens=100,
                ),
            ),
        ),
        Scenario(
            key="conflicting_data",
            description="Two sources disagree about one record; a human must pick.",
            objective="Reconcile the customer tier",
            expect=Expect(proposals=1, escalation="conflicting_outputs"),
            human=HumanBaseline(minutes=30, interventions=2),
            single=(
                propose("root", "p1", "Set tier gold", resource=True),
                propose("root", "p2", "Set tier silver", resource=True),
                done("root"),
            ),
            multi=(
                delegate("root", "d1", "a", "worker_a", "Check CRM tier"),
                delegate("root", "d2", "b", "worker_b", "Check billing tier"),
                propose("a", "p1", "Set tier gold", resource=True),
                propose("b", "p1", "Set tier silver", resource=True),
            ),
        ),
        Scenario(
            key="duplicate_work",
            description="The same objective is handed to two workers.",
            objective="Summarise the account once",
            expect=Expect(proposals=1),
            human=HumanBaseline(minutes=25, interventions=1),
            single=(
                propose("root", "p1", "Account summary"),
                propose("root", "p2", "Account summary"),
                done("root"),
            ),
            multi=(
                delegate("root", "d1", "a", "worker_a", "Summarise account"),
                Op(
                    "root",
                    "d2",
                    "delegate",
                    {"worker": "worker_b", "objective": "  summarise ACCOUNT "},
                    tokens=50,
                    tolerate=True,
                ),
                propose("a", "p1", "Account summary"),
                done("a"),
                done("root"),
            ),
        ),
        Scenario(
            key="budget_pressure",
            description="Three proposals wanted, side-effect budget allows two.",
            objective="Queue three follow-ups",
            expect=Expect(proposals=2, escalation="budget_exhausted"),
            human=HumanBaseline(minutes=30, interventions=2),
            root_side_effects=2,
            single=(
                propose("root", "p1", "Follow-up 1"),
                propose("root", "p2", "Follow-up 2"),
                propose("root", "p3", "Follow-up 3"),
            ),
            multi=(
                delegate("root", "d1", "a", "worker_a", "Follow-ups 1 and 2", side_effect_budget=1),
                delegate("root", "d2", "b", "worker_b", "Follow-up 3", side_effect_budget=1),
                propose("a", "p1", "Follow-up 1"),
                propose("a", "p2", "Follow-up 2"),
                propose("b", "p1", "Follow-up 3"),
                done("b"),
                done("root"),
            ),
        ),
    )
}

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

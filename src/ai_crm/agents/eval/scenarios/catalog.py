from .model import Expect, HumanBaseline, Op, Scenario, delegate, done, propose

__all__ = [
    "SCENARIOS",
]


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

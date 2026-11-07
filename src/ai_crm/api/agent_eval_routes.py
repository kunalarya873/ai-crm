from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..agents.eval import (
    ASSUMPTIONS,
    SCENARIOS,
    aggregate,
    build_comparison,
    latest_comparison,
    list_results,
    run_evaluation,
)
from ..api.deps import RequestContext, require_permission
from ..db import get_session
from ..permissions import Permission
from ..schemas import (
    AgentEvalComparison,
    AgentEvalReport,
    AgentEvalResultRead,
    AgentEvalRunRequest,
    AgentEvalScenarioRead,
)
from .routes import trim_page

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[RequestContext, Depends(require_permission(Permission.AGENTS_READ))]
EvaluateContext = Annotated[
    RequestContext, Depends(require_permission(Permission.AGENTS_EVALUATE))
]


@router.get("/agent-evals/scenarios", response_model=list[AgentEvalScenarioRead], tags=["agents"])
async def list_scenarios_endpoint(context: ReadContext) -> list[AgentEvalScenarioRead]:
    _ = context
    return [
        AgentEvalScenarioRead(
            key=scenario.key,
            description=scenario.description,
            objective=scenario.objective,
            expected_proposals=scenario.expect.proposals,
            expected_escalation=scenario.expect.escalation,
            human_baseline_minutes=scenario.human.minutes,
            human_baseline_interventions=scenario.human.interventions,
            human_baseline_is_assumption=scenario.human.assumption,
        )
        for scenario in SCENARIOS.values()
    ]


@router.post("/agent-evals/run", response_model=AgentEvalReport, tags=["agents"])
async def run_evaluation_endpoint(
    payload: AgentEvalRunRequest, session: SessionDependency, context: EvaluateContext
) -> AgentEvalReport:
    report = await run_evaluation(session, context, payload.scenario_key, payload.replay_key)
    return AgentEvalReport(
        replay_key=payload.replay_key,
        comparisons=[
            AgentEvalComparison(**build_comparison(scenario, results))
            for scenario, results in report
        ],
        aggregate=aggregate(report),
        assumptions=ASSUMPTIONS,
    )


@router.get("/agent-evals/results", response_model=list[AgentEvalResultRead], tags=["agents"])
async def list_results_endpoint(
    response: Response,
    session: SessionDependency,
    context: ReadContext,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = None,
    scenario_key: str | None = None,
) -> list[AgentEvalResultRead]:
    rows = await list_results(
        session,
        context,
        limit=limit + 1,
        offset=offset,
        cursor=cursor,
        scenario_key=scenario_key,
    )
    return [AgentEvalResultRead.model_validate(row) for row in trim_page(response, rows, limit)]


@router.get("/agent-evals/compare", response_model=AgentEvalComparison, tags=["agents"])
async def compare_endpoint(
    scenario_key: str,
    session: SessionDependency,
    context: ReadContext,
    replay_key: str | None = None,
) -> AgentEvalComparison:
    scenario, results = await latest_comparison(session, context, scenario_key, replay_key)
    return AgentEvalComparison(**build_comparison(scenario, results))

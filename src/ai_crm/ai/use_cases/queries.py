from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...domain import NotFoundError
from ...models import AIFeedback, AIRun
from ...schemas import AIFeedbackCreate, AIFeedbackRead, AIProviderHealthRead, AIRunRead
from ..gateway import AIModelGateway
from ..providers import ProviderError

__all__ = [
    "QueryMixin", "feedback_read", "run_read",
]


class QueryMixin:
    gateway: AIModelGateway

    async def get_run(
        self,
        session: AsyncSession,
        context: RequestContext,
        run_id: str,
    ) -> AIRun:
        run = await session.scalar(
            select(AIRun).where(
                AIRun.id == run_id,
                AIRun.tenant_id == context.tenant_id,
            )
        )
        if run is None:
            raise NotFoundError("AI run not found")
        return run

    async def list_runs(
        self,
        session: AsyncSession,
        context: RequestContext,
        *,
        limit: int,
        offset: int,
        use_case: str | None = None,
        run_status: str | None = None,
    ) -> list[AIRun]:
        statement = select(AIRun).where(AIRun.tenant_id == context.tenant_id)
        if use_case:
            statement = statement.where(AIRun.use_case == use_case)
        if run_status:
            statement = statement.where(AIRun.status == run_status)
        result = await session.scalars(
            statement.order_by(AIRun.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result)

    async def record_feedback(
        self,
        session: AsyncSession,
        context: RequestContext,
        run_id: str,
        payload: AIFeedbackCreate,
    ) -> AIFeedback:
        run = await self.get_run(session, context, run_id)
        feedback = AIFeedback(
            tenant_id=context.tenant_id,
            ai_run_id=run.id,
            actor_id=context.actor_id,
            feedback_type=payload.feedback_type,
            edited_output=payload.edited_output,
            correction_note=payload.correction_note,
        )
        session.add(feedback)
        await record_audit(
            session,
            context,
            "ai.feedback.recorded",
            "ai_run",
            run.id,
            details={"feedback_type": payload.feedback_type},
        )
        await record_outbox_event(
            session,
            context,
            "ai.feedback.recorded",
            "ai_run",
            run.id,
            {"feedback_type": payload.feedback_type},
        )
        await session.commit()
        await session.refresh(feedback)
        return feedback

    async def provider_health(self) -> AIProviderHealthRead:
        try:
            detail = await self.gateway.health()
            health_status = "healthy"
        except ProviderError as error:
            detail = str(error)
            health_status = "unhealthy"
        return AIProviderHealthRead(
            provider_key=self.gateway.provider.provider_key,
            model_key=self.gateway.provider.model_key,
            status=health_status,
            detail=detail,
        )


def feedback_read(feedback: AIFeedback) -> AIFeedbackRead:
    return AIFeedbackRead.model_validate(feedback)


def run_read(run: AIRun) -> AIRunRead:
    return AIRunRead.model_validate(run)

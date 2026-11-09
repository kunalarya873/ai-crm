import json

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...audit import record_audit, record_outbox_event
from ...models import AIRun, utc_now
from ..prompts import PromptDefinition
from .constants import RESPONSE_MODELS
from .output import OutputMixin

__all__ = [
    "RunMixin",
]


class RunMixin(OutputMixin):
    async def _finish_run(
        self,
        session: AsyncSession,
        context: RequestContext,
        run: AIRun,
        output: BaseModel,
        *,
        status: str,
        validation_status: str,
        fallback_reason: str | None,
    ) -> None:
        output_data = output.model_dump(mode="json")
        run.status = status
        run.validation_status = validation_status
        run.output = output_data
        run.output_text = json.dumps(output_data, default=str)
        run.evidence_refs = output_data.get("evidence", [])
        run.confidence = output_data.get("confidence")
        run.uncertainty = output_data.get("uncertainty", [])
        run.fallback_reason = fallback_reason
        run.completed_at = utc_now()
        await record_audit(
            session,
            context,
            "ai.run.completed",
            "ai_run",
            run.id,
            outcome="success" if status == "succeeded" else "fallback",
            reason=fallback_reason,
            details={
                "use_case": run.use_case,
                "status": status,
                "validation_status": validation_status,
                "total_tokens": run.total_tokens,
                "estimated_cost_micros": run.estimated_cost_micros,
            },
        )
        await record_outbox_event(
            session,
            context,
            "ai.run.completed",
            "ai_run",
            run.id,
            {"use_case": run.use_case, "status": status},
        )

    def _response_from_run(self, run: AIRun, prompt: PromptDefinition) -> BaseModel:
        model = RESPONSE_MODELS[run.use_case]
        if run.output:
            return model.model_validate(run.output)
        return self._fallback_output(
            run.use_case,
            run.id,
            prompt,
            run.context_assembly_id,
            run.provider_key,
            run.model_key,
            reason=run.fallback_reason or "stored_run_has_no_output",
            evidence=run.evidence_refs,
        )

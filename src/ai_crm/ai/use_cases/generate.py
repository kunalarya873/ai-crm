import time
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...domain import InvalidRequestError
from ...models import AIRun
from ..gateway import AIModelGateway
from ..prompts import PromptDefinition
from ..providers import ProviderError
from .prep import PrepMixin
from .runs import RunMixin

__all__ = [
    "GenerateMixin",
]


class GenerateMixin(RunMixin, PrepMixin):
    gateway: AIModelGateway

    async def _insufficient_evidence(
        self,
        session: AsyncSession,
        context: RequestContext,
        run: AIRun,
        use_case: str,
        prompt: PromptDefinition,
        evidence: list[dict[str, Any]],
    ) -> BaseModel:
        run.error_code = "insufficient_evidence"
        run.error_detail = "No authorised indexed context matched the request"
        output = self._fallback_output(
            use_case,
            run.id,
            prompt,
            run.context_assembly_id,
            run.provider_key,
            run.model_key,
            reason="insufficient_authorised_evidence",
            evidence=evidence,
        )
        await self._finish_run(
            session,
            context,
            run,
            output,
            status="fallback",
            validation_status="fallback",
            fallback_reason="insufficient_authorised_evidence",
        )
        run.latency_ms = 0
        await session.commit()
        await session.refresh(run)
        return output

    async def _generate(
        self,
        session: AsyncSession,
        context: RequestContext,
        run: AIRun,
        use_case: str,
        prompt: PromptDefinition,
        request_data: dict[str, Any],
        context_items: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> BaseModel:
        provider_request = self._provider_request(
            prompt,
            use_case,
            request_data,
            context_items,
            evidence,
        )
        started = time.perf_counter()
        try:
            generation = await self.gateway.generate_structured(provider_request)
            run.input_tokens = generation.input_tokens
            run.output_tokens = generation.output_tokens
            run.total_tokens = generation.input_tokens + generation.output_tokens
            run.provider_attempts = generation.attempts
            run.estimated_cost_micros = self._estimate_cost(
                run.total_tokens, generation.input_tokens
            )
            output = self._validate_output(
                use_case,
                run.id,
                prompt,
                run.context_assembly_id,
                run.provider_key,
                run.model_key,
                generation.output,
                evidence,
            )
            self._enforce_output_policy(output, use_case)
            await self._finish_run(
                session,
                context,
                run,
                output,
                status="succeeded",
                validation_status="validated",
                fallback_reason=None,
            )
        except (ProviderError, ValidationError, InvalidRequestError) as error:
            reason = self._failure_reason(error)
            run.error_code = reason
            run.error_detail = str(error)[:500]
            output = self._fallback_output(
                use_case,
                run.id,
                prompt,
                run.context_assembly_id,
                run.provider_key,
                run.model_key,
                reason=reason,
                evidence=evidence,
            )
            await self._finish_run(
                session,
                context,
                run,
                output,
                status="fallback",
                validation_status="fallback",
                fallback_reason=reason,
            )
        run.latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        await session.commit()
        await session.refresh(run)
        return output

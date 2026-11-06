import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import RequestContext
from ..audit import record_audit, record_outbox_event
from ..config import settings
from ..domain import ConflictError, InvalidRequestError, NotFoundError
from ..knowledge import assemble_context
from ..models import AIFeedback, AIPromptVersion, AIRun, utc_now
from ..permissions import Permission
from ..schemas import (
    AICommunicationDraftResponse,
    AIContextRequest,
    AICustomerSummaryResponse,
    AIFeedbackCreate,
    AIFeedbackRead,
    AIFieldExtractionResponse,
    AINextStepResponse,
    AIProviderHealthRead,
    AIRunRead,
    AIWorkflowPlanResponse,
)
from .gateway import AIModelGateway
from .prompts import PromptDefinition, get_prompt_definition
from .providers import FixtureProvider, ProviderError, ProviderTimeoutError

USE_CASES = frozenset(
    {
        "customer_summary",
        "field_extraction",
        "next_step_recommendation",
        "communication_draft",
        "workflow_plan",
    }
)

RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "customer_summary": AICustomerSummaryResponse,
    "field_extraction": AIFieldExtractionResponse,
    "next_step_recommendation": AINextStepResponse,
    "communication_draft": AICommunicationDraftResponse,
    "workflow_plan": AIWorkflowPlanResponse,
}


def _request_hash(use_case: str, request: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"use_case": use_case, "request": request},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _context_request(use_case: str, request: BaseModel) -> AIContextRequest:
    raw_values = request.model_dump()
    values = raw_values.copy()
    values = {
        key: values[key]
        for key in (
            "query",
            "customer_id",
            "workflow_id",
            "task_id",
            "source_types",
            "max_items",
            "max_chars",
            "include_stale",
        )
        if key in values
    }
    if use_case == "next_step_recommendation" and not values.get("query"):
        values["query"] = raw_values.get("goal") or "next step"
    elif use_case == "communication_draft" and not values.get("query"):
        values["query"] = raw_values.get("purpose") or "customer communication"
    elif use_case == "workflow_plan" and not values.get("query"):
        values["query"] = raw_values.get("objective") or "workflow plan"
    elif use_case == "customer_summary" and not values.get("query"):
        values["query"] = "customer summary"
    return AIContextRequest.model_validate(values)


def _context_items(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": item.chunk_id,
            "text": item.text,
            "title": item.title,
            "score": item.score,
            "freshness": item.freshness,
            "citation": item.citation,
        }
        for item in result.items
    ]


def _evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "reference_type": "knowledge_chunk",
            "reference_id": item["chunk_id"],
            "citation": item["citation"],
        }
        for item in items
    ]


def _base_metadata(
    run_id: str,
    run_status: str,
    prompt: PromptDefinition,
    context_assembly_id: str | None,
    provider_key: str,
    model_key: str,
    confidence: float,
    uncertainty: list[str],
    evidence: list[dict[str, Any]],
    fallback_reason: str | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": run_status,
        "provider_key": provider_key,
        "model_key": model_key,
        "prompt_version": prompt.version,
        "context_assembly_id": context_assembly_id,
        "confidence": max(0, min(1, confidence)),
        "uncertainty": uncertainty,
        "evidence": evidence,
        "insufficient_evidence": not bool(evidence),
        "fallback_reason": fallback_reason,
    }


class AIUseCaseService:
    def __init__(self, gateway: AIModelGateway | None = None) -> None:
        self.gateway = gateway or AIModelGateway(FixtureProvider())

    async def execute(
        self,
        session: AsyncSession,
        context: RequestContext,
        *,
        use_case: str,
        request: BaseModel,
        idempotency_key: str,
        feature_flag: str = "ai_enabled",
    ) -> BaseModel:
        if use_case not in USE_CASES:
            raise InvalidRequestError(f"Unsupported AI use case: {use_case}")
        if Permission.KNOWLEDGE_CONTEXT not in context.permissions:
            raise InvalidRequestError("AI use requires knowledge context permission")
        if not idempotency_key.strip():
            raise InvalidRequestError("Idempotency-Key header is required")

        prompt = get_prompt_definition(use_case)
        request_data = request.model_dump(mode="json")
        request_hash = _request_hash(use_case, request_data)
        existing = await session.scalar(
            select(AIRun).where(
                AIRun.tenant_id == context.tenant_id,
                AIRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError("Idempotency-Key was reused for a different AI request")
            return self._response_from_run(existing, prompt)

        await self._ensure_prompt_version(session, prompt)
        run = AIRun(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            use_case=use_case,
            provider_key=self.gateway.provider.provider_key,
            model_key=self.gateway.provider.model_key,
            config_version=settings.ai_config_version,
            prompt_version=prompt.version,
            prompt_hash=prompt.template_hash,
            feature_flag=feature_flag,
            request=request_data,
            status="running",
            started_at=utc_now(),
        )
        session.add(run)
        await session.flush()

        context_items: list[dict[str, Any]] = []
        context_payload = _context_request(use_case, request)
        context_result = await assemble_context(
            session,
            context,
            self._as_knowledge_request(context_payload),
        )
        context_items = _context_items(context_result)
        run.context_assembly_id = context_result.assembly.id
        run.context_refs = context_items

        evidence = _evidence(context_items)
        if use_case == "field_extraction" and request_data.get("text"):
            text_hash = hashlib.sha256(str(request_data["text"]).encode()).hexdigest()
            evidence = [
                {
                    "reference_type": "request_text",
                    "reference_id": text_hash,
                    "citation": {"input": "user_supplied_text"},
                }
            ]
            run.context_refs = evidence
        requires_context = use_case in {
            "customer_summary",
            "next_step_recommendation",
            "communication_draft",
            "workflow_plan",
        } or (use_case == "field_extraction" and not request_data.get("text"))
        if requires_context and not context_items:
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

    async def _ensure_prompt_version(
        self,
        session: AsyncSession,
        prompt: PromptDefinition,
    ) -> AIPromptVersion:
        existing = await session.scalar(
            select(AIPromptVersion).where(
                AIPromptVersion.use_case == prompt.use_case,
                AIPromptVersion.version == prompt.version,
            )
        )
        if existing is not None:
            return existing
        record = AIPromptVersion(
            use_case=prompt.use_case,
            version=prompt.version,
            catalog_version=prompt.catalog_version,
            template=prompt.template,
            template_hash=prompt.template_hash,
            output_schema_version=prompt.output_schema_version,
            policy_version=prompt.policy_version,
            active=True,
        )
        session.add(record)
        await session.flush()
        return record

    @staticmethod
    def _as_knowledge_request(payload: AIContextRequest) -> Any:
        from ..schemas import KnowledgeContextRequest

        return KnowledgeContextRequest(
            query=payload.query,
            customer_id=payload.customer_id,
            workflow_id=payload.workflow_id,
            task_id=payload.task_id,
            source_types=payload.source_types,
            max_items=payload.max_items,
            max_chars=payload.max_chars,
            include_stale=payload.include_stale,
        )

    @staticmethod
    def _provider_request(
        prompt: PromptDefinition,
        use_case: str,
        request: dict[str, Any],
        context_items: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> Any:
        from .providers import ProviderRequest

        return ProviderRequest(
            use_case=use_case,
            prompt=prompt.template,
            input_data={**request, "evidence": evidence},
            context_items=context_items,
            max_output_chars=settings.ai_max_output_chars,
        )

    @staticmethod
    def _estimate_cost(total_tokens: int, input_tokens: int) -> int:
        output_tokens = max(total_tokens - input_tokens, 0)
        input_units = (input_tokens + 999) // 1000
        output_units = (output_tokens + 999) // 1000
        return (
            input_units * settings.ai_cost_per_1k_input_micros
            + output_units * settings.ai_cost_per_1k_output_micros
        )

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        if isinstance(error, ProviderTimeoutError):
            return "provider_timeout"
        if isinstance(error, ValidationError):
            return "structured_output_invalid"
        if isinstance(error, InvalidRequestError):
            return "output_policy_rejected"
        return "provider_error"

    @staticmethod
    def _enforce_output_policy(output: BaseModel, use_case: str) -> None:
        serialized = json.dumps(output.model_dump(mode="json"), default=str)
        if len(serialized) > settings.ai_max_output_chars:
            raise InvalidRequestError("AI output exceeds the configured length limit")
        forbidden_phrases = (
            "ignore previous instructions",
            "execute shell",
            "drop table",
            "delete all records",
        )
        if any(phrase in serialized.casefold() for phrase in forbidden_phrases):
            raise InvalidRequestError("AI output contains a forbidden command pattern")
        if use_case == "workflow_plan":
            for action in output.model_dump().get("proposed_actions", []):
                if action.get("requires_approval") is not True:
                    raise InvalidRequestError("Workflow actions must require approval")

    @staticmethod
    def _validate_output(
        use_case: str,
        run_id: str,
        prompt: PromptDefinition,
        context_assembly_id: str | None,
        provider_key: str,
        model_key: str,
        output: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> BaseModel:
        model = RESPONSE_MODELS[use_case]
        output_data = dict(output)
        confidence_value = output_data.pop("confidence", 0.0)
        try:
            confidence = float(confidence_value)
        except (TypeError, ValueError) as error:
            raise InvalidRequestError("AI confidence must be numeric") from error
        metadata = _base_metadata(
            run_id,
            "succeeded",
            prompt,
            context_assembly_id,
            provider_key,
            model_key,
            confidence,
            list(output_data.pop("uncertainty", [])),
            output_data.pop("evidence", evidence) or evidence,
            None,
        )
        return model.model_validate({**output_data, **metadata})

    @staticmethod
    def _fallback_output(
        use_case: str,
        run_id: str,
        prompt: PromptDefinition,
        context_assembly_id: str | None,
        provider_key: str,
        model_key: str,
        *,
        reason: str,
        evidence: list[dict[str, Any]],
    ) -> BaseModel:
        metadata = _base_metadata(
            run_id,
            "fallback",
            prompt,
            context_assembly_id,
            provider_key,
            model_key,
            0.0,
            [reason],
            evidence,
            reason,
        )
        if use_case == "customer_summary":
            return AICustomerSummaryResponse(
                **metadata,
                summary="I could not produce a grounded customer summary from authorised evidence.",
                key_points=[],
            )
        if use_case == "field_extraction":
            return AIFieldExtractionResponse(
                **metadata,
                fields={},
                missing_fields=[],
            )
        if use_case == "next_step_recommendation":
            return AINextStepResponse(
                **metadata,
                recommendation="Review the customer record manually before choosing a next step.",
                rationale=(
                    "The available authorised evidence is insufficient for a grounded "
                    "recommendation."
                ),
                priority="normal",
                proposed_work_item=None,
            )
        if use_case == "communication_draft":
            return AICommunicationDraftResponse(
                **metadata,
                channel="email",
                subject=None,
                body=(
                    "No grounded draft is available. Review the customer record and write "
                    "the message manually."
                ),
            )
        return AIWorkflowPlanResponse(
            **metadata,
            objective="",
            steps=[],
            proposed_actions=[],
        )

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


def feedback_read(feedback: AIFeedback) -> AIFeedbackRead:
    return AIFeedbackRead.model_validate(feedback)


def run_read(run: AIRun) -> AIRunRead:
    return AIRunRead.model_validate(run)

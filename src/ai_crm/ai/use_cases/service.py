import hashlib
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import RequestContext
from ...config import settings
from ...domain import ConflictError, InvalidRequestError
from ...flags import require_capability
from ...knowledge import assemble_context
from ...models import AIRun, utc_now
from ...permissions import Permission
from ..gateway import AIModelGateway
from ..prompts import get_prompt_definition
from ..providers import FixtureProvider
from .constants import USE_CASES, _request_hash
from .context import _context_items, _context_request, _evidence
from .generate import GenerateMixin
from .queries import QueryMixin

__all__ = [
    "AIUseCaseService",
]


class AIUseCaseService(GenerateMixin, QueryMixin):
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
        await require_capability(session, context, "ai", operation=f"ai.{use_case}")
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
            return await self._insufficient_evidence(
                session, context, run, use_case, prompt, evidence
            )

        return await self._generate(
            session, context, run, use_case, prompt, request_data, context_items, evidence
        )

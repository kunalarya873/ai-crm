from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...models import AIPromptVersion
from ...schemas import AIContextRequest
from ..prompts import PromptDefinition

__all__ = [
    "PrepMixin",
]


class PrepMixin:
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
        from ...schemas import KnowledgeContextRequest

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
        from ..providers import ProviderRequest

        return ProviderRequest(
            use_case=use_case,
            prompt=prompt.template,
            input_data={**request, "evidence": evidence},
            context_items=context_items,
            max_output_chars=settings.ai_max_output_chars,
        )

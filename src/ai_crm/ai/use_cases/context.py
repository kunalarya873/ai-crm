from typing import Any

from pydantic import BaseModel

from ...schemas import AIContextRequest
from ..prompts import PromptDefinition

__all__ = [
    "_base_metadata", "_context_items", "_context_request", "_evidence",
]


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

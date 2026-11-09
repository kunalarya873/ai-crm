import re
from typing import Any

from .base import ProviderRequest


def customer_summary(
    request: ProviderRequest, context_text: str, evidence: list[Any]
) -> dict[str, Any]:
    points = [
        item.get("text", "").strip()
        for item in request.context_items
        if item.get("text", "").strip()
    ]
    return {
        "summary": context_text or "No authorised customer facts were available.",
        "key_points": points[:5],
        "confidence": 0.92 if points else 0.2,
        "uncertainty": [] if points else ["authorised_context_missing"],
        "evidence": evidence,
    }


def field_extraction(
    request: ProviderRequest, context_text: str, evidence: list[Any]
) -> dict[str, Any]:
    text = str(request.input_data.get("text") or context_text)
    fields = request.input_data.get("fields") or ["email", "phone", "company"]
    extracted: dict[str, Any] = {}
    missing: list[str] = []
    for field in fields:
        value = extract_field(field, text)
        extracted[field] = value
        if value is None:
            missing.append(field)
    return {
        "fields": extracted,
        "missing_fields": missing,
        "confidence": 0.9 if extracted and not missing else 0.65,
        "uncertainty": ["requested_value_not_present"] if missing else [],
        "evidence": evidence,
    }


def next_step_recommendation(
    request: ProviderRequest, context_text: str, evidence: list[Any]
) -> dict[str, Any]:
    recommendation = (
        "Review the cited customer facts and confirm the next commitment with the owner."
    )
    return {
        "recommendation": recommendation,
        "rationale": context_text[:500] or "No authorised context was available.",
        "priority": "normal",
        "proposed_work_item": {
            "item_type": "commitment",
            "title": "Confirm the next customer commitment",
            "requires_human_confirmation": True,
        },
        "confidence": 0.86 if context_text else 0.2,
        "uncertainty": [] if context_text else ["authorised_context_missing"],
        "evidence": evidence,
    }


def extract_field(field: str, text: str) -> str | None:
    normalized = field.casefold()
    if normalized == "email":
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        return match.group(0).rstrip(".,;:") if match else None
    if normalized in {"phone", "phone_number"}:
        match = re.search(r"(?:\+?\d[\d ()-]{7,}\d)", text)
        return match.group(0).strip() if match else None
    if normalized == "company":
        match = re.search(r"(?:company|account)\s*[:=-]\s*([A-Za-z0-9 &.-]+)", text, re.I)
        return match.group(1).strip() if match else None
    return None

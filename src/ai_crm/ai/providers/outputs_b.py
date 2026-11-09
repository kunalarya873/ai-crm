from typing import Any

from ...domain import InvalidRequestError
from .base import ProviderRequest


def communication_draft(
    request: ProviderRequest, context_text: str, evidence: list[Any]
) -> dict[str, Any]:
    purpose = str(request.input_data.get("purpose") or "Follow up")
    recipient = str(request.input_data.get("recipient_name") or "there")
    channel = str(request.input_data.get("channel") or "email")
    return {
        "channel": channel,
        "subject": f"Follow-up: {purpose}" if channel == "email" else None,
        "body": (
            f"Hi {recipient},\n\n"
            f"I am following up regarding {purpose.lower()}. "
            "Please review the details and let me know the next step.\n\n"
            "Best,"
        ),
        "confidence": 0.82 if context_text else 0.35,
        "uncertainty": [] if context_text else ["draft_is_not_context_grounded"],
        "evidence": evidence,
    }


def workflow_plan(
    request: ProviderRequest, context_text: str, evidence: list[Any]
) -> dict[str, Any]:
    objective = str(
        request.input_data.get("objective")
        or "Complete the requested customer follow-up"
    )
    allowed = request.input_data.get("allowed_action_types") or [
        "create_work_item",
        "request_approval",
    ]
    if not isinstance(allowed, list):
        raise InvalidRequestError("allowed_action_types must be a list")
    actions = [
        {
            "action_type": action,
            "parameters": {"objective": objective},
            "requires_approval": True,
        }
        for action in allowed
        if action in {"create_work_item", "request_approval"}
    ]
    return {
        "objective": objective,
        "steps": [
            {
                "step_key": "review_context",
                "title": "Review authorised context",
                "rationale": context_text[:300] or "Confirm the available evidence first.",
                "requires_approval": True,
            },
            {
                "step_key": "confirm_plan",
                "title": "Confirm the proposed next steps",
                "rationale": "A human must approve before any typed action is created.",
                "requires_approval": True,
            },
        ],
        "proposed_actions": actions,
        "confidence": 0.8 if context_text else 0.25,
        "uncertainty": [] if context_text else ["authorised_context_missing"],
        "evidence": evidence,
    }

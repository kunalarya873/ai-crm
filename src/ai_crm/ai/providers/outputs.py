from collections.abc import Callable
from typing import Any

from .base import ProviderRequest
from .outputs_a import customer_summary, field_extraction, next_step_recommendation
from .outputs_b import communication_draft, workflow_plan

OutputBuilder = Callable[[ProviderRequest, str, list[Any]], dict[str, Any]]

OUTPUT_BUILDERS: dict[str, OutputBuilder] = {
    "customer_summary": customer_summary,
    "field_extraction": field_extraction,
    "next_step_recommendation": next_step_recommendation,
    "communication_draft": communication_draft,
    "workflow_plan": workflow_plan,
}

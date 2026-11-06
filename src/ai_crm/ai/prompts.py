import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..config import settings


@dataclass(frozen=True)
class PromptDefinition:
    use_case: str
    version: str
    catalog_version: str
    template: str
    output_schema_version: str
    policy_version: str

    @property
    def template_hash(self) -> str:
        return hashlib.sha256(self.template.encode()).hexdigest()


def _load_catalog() -> dict[str, dict[str, str]]:
    path = Path(__file__).with_name("prompt_catalog.json")
    return json.loads(path.read_text())


def get_prompt_definition(use_case: str) -> PromptDefinition:
    definition = _load_catalog().get(use_case)
    if definition is None:
        raise ValueError(f"Unsupported AI use case: {use_case}")
    return PromptDefinition(
        use_case=use_case,
        version=definition["version"],
        catalog_version=definition["catalog_version"] or settings.ai_prompt_catalog_version,
        template=definition["template"],
        output_schema_version=definition["output_schema_version"],
        policy_version=definition["policy_version"],
    )

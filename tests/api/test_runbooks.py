import re
from pathlib import Path

import pytest

from ai_crm.main import app

RUNBOOKS = Path(__file__).resolve().parents[2] / "docs" / "runbooks"
ENDPOINT = re.compile(r"`(GET|POST|PUT|PATCH|DELETE) (/[^`\s?]+)")
LINK = re.compile(r"\]\(([\w.-]+\.md)\)")


def _documented() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(RUNBOOKS.glob("*.md")):
        for method, route in ENDPOINT.findall(path.read_text()):
            found.append((path.name, method, route))
    return found


def test_runbooks_exist_for_each_support_area() -> None:
    names = {path.name for path in RUNBOOKS.glob("*.md")}

    assert {
        "README.md",
        "failed-jobs.md",
        "failed-syncs.md",
        "failed-actions.md",
        "ai-output-issues.md",
        "data-access-issues.md",
        "stuck-agent-runs.md",
        "kill-switches.md",
    } <= names


@pytest.mark.parametrize(("name", "method", "route"), _documented())
def test_every_documented_endpoint_exists(name: str, method: str, route: str) -> None:
    paths = app.openapi()["paths"]

    operations = paths.get(f"/api/v1{route}")

    assert operations is not None, f"{name}: {route} is not an endpoint"
    assert method.lower() in operations, f"{name}: {method} {route} is not allowed"


def test_runbook_links_resolve_and_index_lists_every_runbook() -> None:
    index = (RUNBOOKS / "README.md").read_text()
    for path in RUNBOOKS.glob("*.md"):
        for target in LINK.findall(path.read_text()):
            assert (RUNBOOKS / target).exists(), f"{path.name} links to missing {target}"
        if path.name != "README.md":
            assert path.name in index, f"{path.name} is not in the index"

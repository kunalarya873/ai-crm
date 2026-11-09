import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "loadtest.py"


def load_harness(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("loadtest_harness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "loadtest_harness", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_smoke_profile_runs_every_phase_without_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checks the harness works, not how fast the app is: there are no timing thresholds."""
    harness = load_harness(monkeypatch)

    report = await harness.run("smoke", None, None, 3, True)

    assert set(report["operations"]) == set(harness.OPERATIONS)
    for name, row in report["operations"].items():
        assert row["errors"] == {}, f"{name} had errors: {row['errors']}"
        assert row["p50_ms"] <= row["p95_ms"] <= row["p99_ms"] <= row["max_ms"]
    assert report["worker_drain"]["jobs_handled"] > 0
    assert report["worker_drain"]["enqueue_rejected"] == 0
    assert report["tick_cost"][0]["jobs_handled_during_ticks"] == 0
    assert report["tick_cost"] and report["tick_cost"][0]["tenants"] >= 2
    assert report["table_scans"] is not None
    assert "contacts.list" in harness.render(report)

import pytest
from pydantic import ValidationError

from ai_crm.config import DEFAULT_AUTH_SECRET_KEY, Settings

STRONG = "x" * 40


def build(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_default_secret_rejected_outside_debug() -> None:
    with pytest.raises(ValidationError):
        build(debug=False, auth_secret_key=DEFAULT_AUTH_SECRET_KEY)


def test_short_secret_rejected_outside_debug() -> None:
    with pytest.raises(ValidationError):
        build(debug=False, auth_secret_key="short")


def test_strong_secret_accepted_outside_debug() -> None:
    assert build(debug=False, auth_secret_key=STRONG).auth_secret_key == STRONG


def test_default_secret_allowed_in_debug() -> None:
    assert (
        build(debug=True, auth_secret_key=DEFAULT_AUTH_SECRET_KEY).auth_secret_key
        == DEFAULT_AUTH_SECRET_KEY
    )


@pytest.mark.parametrize(
    "field", ["worker_poll_seconds", "worker_batch_size", "proactive_check_interval_seconds"]
)
def test_worker_intervals_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        build(debug=True, **{field: 0})

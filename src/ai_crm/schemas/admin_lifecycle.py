from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = ["ErasureRead", "ErasureRequest", "LegalHoldCreate", "LegalHoldRead", "LegalHoldRelease"]


Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class LegalHoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["tenant", "record"]
    resource_type: str | None = Field(default=None, max_length=30)
    record_id: str | None = Field(default=None, max_length=36)
    reason: Reason


class LegalHoldRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class LegalHoldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope: str
    resource_type: str | None
    record_id: str | None
    reason: str
    created_by: str
    created_at: datetime
    released_by: str | None
    released_at: datetime | None
    release_reason: str | None


class ErasureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


class ErasureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    resource_type: str
    record_id: str
    erased_by: str
    reason: str
    erased_at: datetime

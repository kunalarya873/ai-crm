from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, utc_now

__all__ = ["ErasureRecord", "LegalHold"]


class LegalHold(Base):
    """Blocks erasure (and, when tenant-wide, telemetry purges) until released."""

    __tablename__ = "legal_holds"
    __table_args__ = (Index("ix_legal_holds_tenant_released", "tenant_id", "released_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    released_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ErasureRecord(Base):
    """One row per erased CRM record; the unique key makes erasure idempotent."""

    __tablename__ = "erasure_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "resource_type", "record_id", name="uq_erasure_records_record"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    erased_by: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    erased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

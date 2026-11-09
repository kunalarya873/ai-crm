from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Activity, IntegrationConnection, IntegrationRecordLink, utc_now
from .contract import CanonicalActivity

__all__ = [
    "_upsert_activity_record",
]


async def _upsert_activity_record(
    session: AsyncSession,
    connection: IntegrationConnection,
    record: CanonicalActivity,
) -> None:
    link = await session.scalar(
        select(IntegrationRecordLink).where(
            IntegrationRecordLink.connection_id == connection.id,
            IntegrationRecordLink.resource_type == "activity",
            IntegrationRecordLink.provider_record_id == record.provider_record_id,
        )
    )
    source_record_id = f"{connection.external_account_id}:{record.provider_record_id}"
    if link is None:
        activity = Activity(
            tenant_id=connection.tenant_id,
            kind=record.kind,
            subject=record.subject,
            body=record.body,
            event_at=record.provider_updated_at,
            ingested_at=utc_now(),
            actor_id="integration:fixture",
            source_system=connection.provider_key,
            source_record_id=source_record_id,
        )
        session.add(activity)
        await session.flush()
        link = IntegrationRecordLink(
            connection_id=connection.id,
            resource_type="activity",
            provider_record_id=record.provider_record_id,
            canonical_type="activity",
            canonical_id=activity.id,
            source_url=record.source_url,
            provider_updated_at=record.provider_updated_at,
            provenance={
                "provider_key": connection.provider_key,
                "external_account_id": connection.external_account_id,
            },
        )
        session.add(link)
    else:
        activity = await session.get(Activity, link.canonical_id)
        if activity is not None and (
            link.provider_updated_at is None
            or record.provider_updated_at > link.provider_updated_at
        ):
            activity.kind = record.kind
            activity.subject = record.subject
            activity.body = record.body
            activity.event_at = record.provider_updated_at
        link.source_url = record.source_url
        link.provider_updated_at = record.provider_updated_at
        link.deleted_at = utc_now() if record.deleted else None
    link.last_seen_at = utc_now()

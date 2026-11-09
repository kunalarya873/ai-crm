# Data lifecycle: audit lookup, export, telemetry purge, legal holds, erasure

All three need the `admin` role. Each call is itself audited.

**Investigate who did what**
`GET /admin/audit-events` filters by `actor_id`, `entity_type`, `entity_id`, `action`, `outcome`,
`correlation_id`, `since` and `until`. Newest first; follow `X-Next-Cursor` with `?cursor=`.
Denied attempts are `outcome=denied`. The lookup writes an `audit.queried` row with the filters.

**Export a tenant's records**
`GET /admin/export/{resource}` where resource is `contacts`, `companies`, `opportunities`,
`activities` or `tasks`. Archived records are included. Pages are at most 500 rows; keep calling
with `?cursor=<X-Next-Cursor>` until the header is absent. Each page writes an `export.read` row.
Connections, secrets, members and knowledge are not exportable here.

**Purge old telemetry**
1. Dry run (the default): `POST /admin/retention/purge` with `{}` shows how many rows would go.
2. Real run: `{"dry_run": false}`. `older_than_days` defaults to `OBSERVABILITY_RETENTION_DAYS`
   and cannot be lower. Each table is capped at `RETENTION_PURGE_BATCH_SIZE` per call: if
   `truncated` is true, run it again until the counts reach zero.
3. Only operational events, metric observations, resolved alerts and published outbox rows are
   deleted. Audit events and CRM records are never purged. The run writes `retention.purged`.

Deletion is permanent. Record who ran it, the cutoff and the counts.

**Place or release a legal hold**
`POST /admin/legal-holds` with `{"scope": "tenant", "reason": "..."}` or `{"scope": "record",
"resource_type": "contacts", "record_id": "<id>", "reason": "..."}` (resources: contacts,
companies, opportunities, activities, tasks). While a hold is active, erasure of the held record
(or of any record, for a tenant hold) and real telemetry purges (tenant hold) are refused with 409
`legal_hold`; the refused attempt is audited. Normal edits still work. List with
`GET /admin/legal-holds?active=true`; release with `POST /admin/legal-holds/{hold_id}/release` and a
reason. Placing and releasing are audited.

**Erase a person's record**
1. Check for holds: `GET /admin/legal-holds?active=true`.
2. `POST /admin/erasure/{resource}/{record_id}` with `{"reason": "..."}`. Personal fields become
   `[erased]` or empty, the record is archived and its version increments, and its id and links stay.
   Repeating the call returns the original erasure, and the record can no longer be edited or
   un-archived. External ids (for example `source_record_id`) are kept so a re-sync does not
   recreate it. Do not put personal data in the reason: audit events are never purged.
3. Erase each related record separately (the contact, their activities and tasks). Copies in
   knowledge sources, AI run records, operational events, earlier exports and backups are not
   changed by this call; the `record.erased` outbox event is there for downstream systems.

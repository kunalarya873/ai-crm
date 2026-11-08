# Data lifecycle: audit lookup, export, telemetry purge

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

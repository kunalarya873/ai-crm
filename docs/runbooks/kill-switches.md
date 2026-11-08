# Kill switches

Four capabilities can be switched off: `ai`, `workflows`, `connectors`, `agents`.

**Per tenant (admin):**

1. See the state: `GET /admin/feature-flags` (admin and manager). Note each flag's `version`.
2. Disable: `PUT /admin/feature-flags/{flag}` with `{"enabled": false, "reason": "<incident id>"}`
   and `If-Match: "<version>"` (use `"0"` the first time). The reason is required.
3. Verify: new work returns `503 capability_disabled` and a `capability.blocked` audit row is
   written; reads still work.
4. Re-enable: `PUT` again with `{"enabled": true}` and the new `ETag` version.

**All tenants (operator):** set `DISABLED_CAPABILITIES=ai,agents` (comma-separated) and restart.
It wins over any tenant setting and shows as `source: platform`.

**What keeps working while off:** reads, AI feedback, disconnecting or revoking a connection, and
pausing or cancelling agent runs. Queued connector jobs wait instead of failing.

Record who switched what off, why, and when it was turned back on.

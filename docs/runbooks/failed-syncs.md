# Failed syncs and connection problems

**Signals:** `sync_freshness_seconds` breached; a `connection_needs_reauth` alert; syncs failing.

1. List connections and their status: `GET /integrations/connections`.
2. Recent attempts: `GET /integrations/connections/{connection_id}/sync-runs`. A transient
   `failure_code` backs off automatically; a permanent one pauses scheduled syncs for that
   connection until a manual sync succeeds.
3. `needs_reauth`: the provider rejected the token. Re-issue the credential at the provider, then
   `POST /integrations/connections/{connection_id}/refresh` or
   `POST /integrations/connections/{connection_id}/test`; either restores `connected`.
4. Run a sync by hand: `POST /integrations/connections/{connection_id}/sync` (it is idempotent
   while one is already running).
5. Stop the bleeding: `POST /integrations/connections/{connection_id}/disconnect` (reversible by
   `test`), or `POST /integrations/connections/{connection_id}/revoke` (terminal).
6. If the provider is down for everyone, switch the `connectors` capability off (see
   [kill-switches.md](kill-switches.md)) so jobs wait instead of failing, and resume afterwards.

Webhooks: an invalid signature returns 401, a replay returns `duplicate`, and a webhook for a
disconnected or revoked connection returns 409. None of these need operator action.

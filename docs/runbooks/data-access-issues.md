# Data-access issues

**Signals:** "I cannot see X", "I can change Y but should not", or a suspected cross-tenant leak.

1. Check who they are in this tenant: `GET /admin/members` (admin or manager). Look at `role` and
   `is_active`.
2. Denials are audited. Look for `authorization.denied` and `capability.blocked`:
   `GET /observability/events?event_type=authorization.denied`.
3. Role changes: `PATCH /admin/members/{membership_id}` with `If-Match`. A tenant must keep at
   least one active admin. Deactivation takes effect on the user's next request.
4. Knowledge visibility is per source (`visibility`, `sensitivity`, `ai_allowed`): inspect with
   `GET /knowledge/sources/{source_id}`. Sensitive sources need `knowledge:sensitive`
   (manager and admin).
5. Suspected cross-tenant exposure is a security incident: switch off the affected capability
   ([kill-switches.md](kill-switches.md)), keep the correlation and trace ids, and escalate to the
   SLO owner. Every query is tenant-filtered and cross-tenant lookups return 404; any deviation is a
   bug to be fixed with a regression test.
6. Sharing a user between tenants is intentional (one account, several memberships); it never
   shares data.

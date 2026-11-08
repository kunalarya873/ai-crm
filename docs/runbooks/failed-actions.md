# Failed, recoverable or uncertain actions

**Signals:** `action_completion_rate` breached; an execution in `failed`, `recoverable` or
`uncertain`.

1. List them: `GET /actions/executions?status=uncertain` (also `failed`, `recoverable`).
2. Open one: `GET /actions/executions/{execution_id}`. `uncertain_outcome` means the external
   system may or may not have applied the change.
3. **Never retry an uncertain execution first.** Reconcile it: check the external system, then
   `POST /actions/executions/{execution_id}/reconcile` with an `operator_note` recording what you
   found.
4. Only after reconciliation, or for a plain `failed` / `recoverable` execution with a known
   cause that is fixed: `POST /actions/executions/{execution_id}/retry`.
5. Stale approvals: `POST /actions/proposals/expire` expires proposals past their deadline;
   `POST /actions/proposals/{proposal_id}/revoke` withdraws one that should not run.
6. Re-check the record version: executions fail with a version conflict if the target record
   changed after approval. That is correct; propose a fresh action.

Approval needs `actions:approve`, and neither the requester nor the last editor of a proposal may
approve it.

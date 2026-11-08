# Stuck or escalated agent runs

**Signals:** `agent_overdue_runs` breached; a run in `waiting_human`; an escalation work item.

1. Find them: `GET /agent-runs?status=waiting_human` (also `running`, `paused`).
2. Read one: `GET /agent-runs/{run_id}` for steps and budgets, and
   `GET /agent-runs/{run_id}/messages` for the persisted delegation, result and escalation
   messages.
3. Escalations create a work item (`escalation_work_item_id`): `GET /work-items/{work_item_id}`.
   Resolve it with `POST /work-items/{work_item_id}/transition` to `completed` (evidence required).
4. Resume only once the work item is completed: `POST /agent-runs/{run_id}/resume` with
   `If-Match`. It fails while the agent is suspended or the deadline has passed.
5. Wind down: `POST /agent-runs/{run_id}/pause` or `POST /agent-runs/{run_id}/cancel`. Cancelling
   stops every active descendant run. A parent that fails or runs out of budget also stops its
   children.
6. Overdue runs are failed by the worker on its next tick; if the worker is down, restart it
   (see [failed-jobs.md](failed-jobs.md)).
7. A misbehaving agent: `PATCH /agents/{agent_id}` with `{"status": "suspended"}` (admin only).
   Agents can only propose actions; nothing executes without human approval.
8. To stop all agent work, switch off `agents` ([kill-switches.md](kill-switches.md)); pause,
   cancel and reads still work.

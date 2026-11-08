# Bad, slow or missing AI output

**Signals:** `ai_fallback_rate` or `ai_avg_latency_ms` breached; a user reports a wrong answer.

1. Find the run: `GET /ai/runs` and `GET /ai/runs/{run_id}`. The run records the prompt and model
   versions, the evidence references, the validated output and any `fallback_reason`.
2. Wrong answer with evidence: check the cited sources (`GET /knowledge/sources/{source_id}`);
   fix or archive the source with `PATCH /knowledge/sources/{source_id}` and re-index it with
   `POST /knowledge/sources/{source_id}/index`.
3. Insufficient evidence is a valid result, not a failure: the system declines instead of
   guessing.
4. Record the correction: `POST /ai/runs/{run_id}/feedback`. Feedback feeds the human-intervention
   metric.
5. Provider trouble: `GET /ai/providers/health`. Repeated fallbacks with a healthy provider point
   at a prompt or context problem.
6. AI output is reviewable data and never an effect by itself; anything consequential still goes
   through the action approval path.
7. To stop AI generation tenant-wide, switch off `ai` (see [kill-switches.md](kill-switches.md)).
   Reading earlier runs and giving feedback keep working.

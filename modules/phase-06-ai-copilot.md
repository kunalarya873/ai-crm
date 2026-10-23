# Phase 06 — Grounded AI Copilot

## Goal

Reduce repetitive knowledge work while keeping the user in control. AI outputs must be grounded in authorised context, distinguish facts from suggestions, and be easy to review or correct.

## Modules

### M06.1 — AI gateway and model abstraction

- Centralise model calls, provider configuration, timeouts, token/cost accounting, and failure handling.
- Record model, prompt/template version, retrieval references, latency, usage, and result status.
- Keep application logic independent of a single model provider where practical.

### M06.2 — Customer and activity summaries

- Generate concise summaries of customer history, recent activity, open work, risks, and next steps.
- Show citations or source references for factual claims.
- Indicate missing or conflicting data.

### M06.3 — Information extraction and record assistance

- Extract structured fields from conversations, notes, forms, and documents.
- Present extracted changes as a reviewable diff before saving.
- Allow users to correct, reject, or accept individual fields.

### M06.4 — Recommendations and next steps

- Recommend prioritisation, follow-up timing, missing information, or likely next actions for the target workflow.
- Separate observed facts, rules, and model-generated recommendations.
- Provide an explanation based on retrieved evidence and uncertainty.

### M06.5 — Communication drafting

- Draft emails or messages using approved customer context, organisational knowledge, and tone controls.
- Never send directly in this phase.
- Show source context, editable draft, missing information, and policy warnings.

### M06.6 — AI evaluation and feedback

- Create offline evaluations for groundedness, relevance, extraction accuracy, unsafe suggestions, and permission leakage.
- Capture user edits, acceptance, rejection, correction, and feedback.
- Add prompt/model version comparison before changing production defaults.

## Deliverables

- AI gateway with usage and audit records.
- Grounded summaries and extraction flows.
- Reviewable recommendations and communication drafts.
- Evaluation dataset, scoring process, and feedback loop.
- User-visible evidence and uncertainty states.

## Dependencies

Phases 01–05, especially permission-aware retrieval and work-item models.

## Exit criteria

- AI responses use only authorised context.
- Important factual claims can be traced to source evidence or are marked as uncertain.
- Users can review, edit, reject, and correct generated output before it changes records or leaves the system.
- AI failures degrade safely and do not block manual work.
- Quality, latency, usage cost, and human acceptance are measurable for the target workflow.

## Do not build yet

- Unreviewed outbound messages.
- Autonomous record deletion or high-impact changes.
- A general-purpose assistant unrelated to the target workflow.

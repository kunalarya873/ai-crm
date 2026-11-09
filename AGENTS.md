# AGENTS.md — AI CRM Backend

Canonical, agent-neutral guide for this repository. Every coding agent (Codex, Claude Code, Gemini CLI / Antigravity, Cursor, Copilot, etc.) should read this file first.
`CLAUDE.md` and `GEMINI.md` import this file and add only tool-specific notes, so **edit shared rules here, not there**.

## 1. What this project is

The runnable backend for an AI-first CRM and business-automation platform. Product intent lives in `Target.md` (PRD); the phased delivery plan lives in `modules/`.

- **Stack:** Python ≥ 3.12, FastAPI, async SQLAlchemy 2.x, SQLite (`aiosqlite`) for local/dev, Alembic, Pydantic v2 / `pydantic-settings`, PyJWT. Package manager: **`uv`**.
- **Status:** Backend Phases 1, 2, 3A, 4, 5A, 6A, 7A, 8A, 9A, 9B are implemented, plus Phase 10A kill switches, 10B SLOs/usage/runbooks and 10C audit lookup/export/telemetry purge and 10D worker fairness/breaker/backpressure 10E CI/migration tests/policy 10F local load harness 10G worker discovery 10H SQLite WAL experiment (opt-in `SQLITE_WAL`) and 10I PostgreSQL test lane (~15k lines in `src/`). **Next slice: the rest of Phase 10 (multi-process capacity evidence, remaining write-path tail latency (WAL helped writes but hurt reads; see docs/capacity.md), per-request telemetry)** (`modules/backend/phase-10-scale-and-production-operations.md`).
- **Local-only boundaries:** the only AI provider is the deterministic `fixture` adapter (no external model calls), the only integration provider is `fixture`, and JWT auth uses a local dev secret. None of this is production-ready; do not describe it as such.

## 2. Commands

Run from the repository root.

```bash
uv sync --extra dev                                           # install
uv run uvicorn ai_crm.main:app --app-dir src --reload         # run API (docs at /docs)
uv run ruff check .                                           # lint (E, F, I, UP; line length 100)
uv run pytest -q                                              # tests (asyncio_mode=auto)
uv run pytest tests/api/test_actions.py -q                    # one file
uv run pytest tests/api/test_actions.py -q -k "<name>"        # one test
uv run alembic upgrade head                                   # apply migrations
uv run alembic downgrade base                                 # must also work (round-trip)
uv run --with pyright pyright                                 # type check
TEST_DATABASE_URL=postgresql+psycopg_async://user@host/db uv run pytest -q   # same suite on PostgreSQL (needs `uv sync --extra postgres`)
```

**Definition of "green" before you report work as done:** `ruff check`, `pytest -q`, `alembic upgrade head` and `alembic downgrade base` (on a throwaway DB), and pyright all pass. If you could not run one, say so explicitly.

Local dev token (needs `DEBUG=true`, `SEED_DEMO_DATA=true`, tenant `demo-tenant`, user `demo-user`):

```bash
TOKEN=$(uv run python -c 'from ai_crm.auth import create_access_token; print(create_access_token("demo-user"))')
```

## 3. Repository map

**File size rule:** no `.py` file under `src/` is longer than 150 lines (`find src -name '*.py' | xargs wc -l | sort -rn | head`). Large modules are packages: `X/__init__.py` re-exports every public name from small submodules (`from .part import *`), so import paths such as `ai_crm.services`, `ai_crm.models`, `ai_crm.schemas`, `ai_crm.integrations`, `ai_crm.actions.service`, `ai_crm.agents.runs`, `ai_crm.work.jobs`, `ai_crm.flags` are unchanged. Router packages (`api/*_routes/`) share one `router` defined in `base.py`; keep `__init__` import order (it is the route order). The names tests monkeypatch stay in thin modules and are passed to the code in sub-packages: `work/runner.py` (breaker, `create_job`, `disabled_flags`, `tenants_with_work`; helpers in `work/tick/`) and `api/ai_routes.py` (`service`, read per call by `api/ai_endpoints/`). The paths below name the package or module; open the directory for the parts.

```
src/ai_crm/
  main.py            App factory, lifespan, router mounting; middleware.py = correlation-ID middleware + security headers; error_handlers.py = DomainError -> HTTP mapping
                     (the single place status codes are decided; handlers registered in main.py)
  config.py          Settings (pydantic-settings; env/.env). Every new knob is added here AND in .env.example
  db.py              Async engine/session, create_tables, seed_local_identity, configure_sqlite (busy_timeout; opt-in WAL via SQLITE_WAL)
  models.py          All SQLAlchemy models (single Base)
  schemas.py         Pydantic request/response schemas
  domain.py          DomainError hierarchy, status enums, allowed-transition tables
  members.py         Tenant member/role administration (last-admin protection)
  usage.py           Phase 10B per-tenant admin usage read model (GET /admin/usage)
  audit_query.py / export.py / retention.py   Phase 10C: audit lookup, tenant export, telemetry-only purge (never audit events or CRM rows); admin-only
  flags.py           Phase 10A kill switches: ai/workflows/connectors/agents, tenant flags + DISABLED_CAPABILITIES; call require_capability() before *new* work, never on reads or wind-down
  pagination.py      Keyset cursor helpers for list endpoints
  permissions.py     Permission enum + ROLE_PERMISSIONS (admin = all; manager = member + approve/recover/integration-write/sensitive/observability-manage + read members, explicit allowlist; member = read/write CRM + propose/execute actions; viewer = read-only + AI use; only admin has `integrations:manage`, `admin:members:manage` and `agents:manage`, `agents:evaluate` and `admin:flags:manage` (managers read flags); viewers read agents, members and managers run them)
  auth.py            Local JWT creation/decoding
  audit.py           record_audit, record_outbox_event (also mirrors to OperationalEvent, with redaction)
  services.py        Core CRM services (contacts, companies, opportunities, activities, tasks, timelines)
  integrations.py    Provider-neutral connector contract, fixture connector, webhook signature checks
  api/               Thin routers: routes.py, integration_/knowledge_/work_/ai_/action_/observability_/admin_/agent_routes.py
                     deps.py = RequestContext, get_request_context, require_permission
  knowledge/         Source registry, versioned indexing jobs, permission-aware lexical retrieval, context assembly
  work/              Work items, durable jobs (leases/retries/dead-letter), allowlisted workflows;
                     handlers.py = job-type allowlist, runner.py = opt-in in-process worker (WORKER_ENABLED; rotating tenant order, per-tenant time budget; tenants_with_work() discovery so idle tenants are not visited); breaker.py = in-process connector circuit breaker; create_job sheds with 429 at MAX_QUEUED_JOBS_PER_TENANT
  ai/                Gateway, provider adapters (fixture), JSON prompt catalog, typed use cases
  actions/           Typed action registry, proposals, approval, execution, reconciliation
  observability/     Operational events, metrics, proactive checks, alerts, telemetry redaction; slo.py = SLO definitions (owner from SLO_OWNER) and on-demand evaluation
  agents/            Phase 9A/9B (eval/ = scripted replayable scenarios, admin-only, assumptions labelled): agent registry, runs/steps, bounded delegation, human escalation (no model loop; the run owner submits steps; agents only propose, never approve/execute)
alembic/versions/    0001…0016, linear chain; tests/test_migrations.py enforces one head, round-trip and model/migration parity
.github/workflows/ci.yml  ruff + pytest + pyright + Alembic round-trip (not yet run on GitHub)
scripts/loadtest.py  local load harness (in-process, SQLite); docs/capacity.md has the recorded run and findings
docs/migrations.md   expand/contract policy, deploy order, rollback
tests/               tests/conftest.py (isolated temp-DB `client` fixture) + tests/api/test_*.py per area
docs/runbooks/       Operator runbooks; tests/api/test_runbooks.py fails if a named endpoint no longer exists
modules/             Phase plans, exit criteria, development gates (the source of truth for scope)
Target.md            Product requirements
.agents/             Local agent skill library (gitignored; not project source)
```

## 4. Architectural rules (non-negotiable)

These are enforced by existing code and tests. Follow the pattern of the nearest existing module rather than inventing a new one.

### Layering
- **Routers are thin.** Validate input (Pydantic), resolve `RequestContext`, call a service, return a schema. No business rules in `api/`.
- **Business rules live in services/domain modules** (`services.py`, `*/service.py`, `work/*.py`, …). State machines are tables in `domain.py` / `*/domain.py`.
- **Provider SDKs stay behind adapters** (`integrations.py`, `ai/providers.py`). Nothing outside an adapter imports a vendor SDK.
- Raise `DomainError` subclasses (`NotFoundError`, `ConflictError`, `VersionConflictError`, `PreconditionRequiredError`, `InvalidRequestError`, `InvalidTransitionError`); `error_handlers.py` (registered in `main.py`) maps them to 404/409/428/422. Add a new subclass + mapping there rather than raising `HTTPException` from services.

### Tenant isolation and permissions
- Every tenant-owned table has `tenant_id`; **every query filters by it**. Cross-tenant references (e.g., a contact in tenant A linked to a company in tenant B) must be rejected, and there must be a test.
- Requests carry `Authorization: Bearer <jwt>` and `X-Tenant-ID`. Membership is verified in `get_request_context`.
- Gate every endpoint with `require_permission(Permission.X)`. New capability ⇒ add a `Permission` member, decide its role mapping in `ROLE_PERMISSIONS`, test allowed **and** denied (denials are audited as `authorization.denied`).

### Writes
- **Optimistic concurrency:** mutable records have an integer `version`; PATCH requires `If-Match: "<version>"` (missing ⇒ 428, mismatch ⇒ 409), and increments `version`.
- **Audit + outbox:** every successful write calls `record_audit` and, when downstream work depends on it, `record_outbox_event`, in the **same transaction** as the state change. Denied/failed sensitive operations are audited too.
- **Idempotency:** retried or externally-triggered operations carry an idempotency key / dedup key with a unique constraint (jobs, AI runs, action effects, external writes, alerts, reminders). Duplicate delivery must be a no-op returning the original result.
- **Transitions** are validated against the allowed-transition tables; invalid ⇒ `InvalidTransitionError`.

### AI and actions (Gates D and E in `modules/development-gates.md`)
- AI output is **reviewable data, never an effect.** The gateway records prompt/model/config versions, bounded authorised context, evidence references, validated structured output, usage/cost, and a safe fallback on failure.
- Retrieval is **permission-aware**: respect source visibility, sensitivity (`knowledge:sensitive`), AI-use policy, and freshness. If evidence is insufficient, return an insufficient-evidence result instead of guessing.
- Consequential changes go **proposal → (edit) → approve → execute**, using only actions in the typed registry (`actions/registry.py`). Each action declares permissions, risk level, affected resources, expected side effects, and approval policy. Re-check record versions at execution. Uncertain external outcomes must be **reconciled before retry**.
- Workflows are an **allowlist** of typed definitions; job handlers are explicit application operations. Never execute generated code or accept arbitrary handler names from a client.

### Security and data hygiene
- Never log or return secrets. Use opaque `secret_ref` values; route anything telemetry-bound through `redact_telemetry`.
- Webhooks: verify signature, enforce max age, deduplicate (replay protection) before enqueueing.
- External calls need timeouts and bounded retries with backoff.
- Do not weaken the correlation-ID middleware or security headers in `middleware.py`.

## 5. Database and migrations

- Models change ⇒ add a **new** Alembic revision (`alembic/versions/NNNN_phaseN_<slug>.py`) that chains from the current head. Never edit a migration that is already committed/applied; never create a second head.
- Migrations must `upgrade head` **and** `downgrade base` cleanly. Name constraints explicitly (see `uq_operational_events_dedup`).
- Tests build the schema with `Base.metadata.create_all`, so **a model change without a matching migration will pass tests but break `alembic upgrade head`** — always run the Alembic round-trip.
- `AUTO_CREATE_TABLES=true` is a dev convenience only; production-like runs use Alembic.
- `*.db` files are gitignored throwaways. Don't commit them and don't rely on their contents.

## 6. Testing conventions

- Tests are async API tests via `httpx.ASGITransport` against the real app, with an isolated temp SQLite DB per test (`client` fixture in `tests/conftest.py`). Fixture data: tenants `tenant-a`/`tenant-b`; `user-a` is `member` in both; `user-b` is `viewer` in `tenant-a` only; `user-c` is `manager` in `tenant-a`; `user-d` is `admin` in both. Proposers cannot approve their own action proposals (403 `separation_of_duties`).
- Auth helper pattern: `{"Authorization": f"Bearer {create_access_token(user_id)}", "X-Tenant-ID": tenant_id}`.
- Add tests next to the area: `tests/api/test_<area>.py`. For every feature cover happy path, validation errors, **permission denied, cross-tenant isolation, idempotency/duplicate delivery, concurrency (`If-Match`), and failure/recovery paths** (timeouts, retries, partial failure). This mirrors `modules/backend/backend-development-checklist.md`.
- Don't mock the database or the app; use the fixture provider for AI/integration behaviour. Tests must be deterministic (no network, no wall-clock sleeps beyond tiny bounded ones).

## 7. Conventions

- Style: ruff (`E,F,I,UP`, line length 100), full type hints, `from __future__`-free modern syntax (`X | None`, `StrEnum`, `datetime.UTC`).
- Timestamps are timezone-aware UTC. IDs are string UUIDs (`String(36)`); tenant/actor IDs are `String(100)`.
- Config: add the setting in `config.py` **and** `.env.example`; document it in `README.md` if user-visible.
- Routes are mounted under `settings.api_v1_prefix` (`/api/v1`); register new routers in `main.py`.
- Keep `README.md`'s endpoint lists and "Current implementation" section accurate when you add or change endpoints.

## 8. Scope discipline: how to add a feature or phase

1. Read the matching plan in `modules/backend/phase-NN-*.md` (and the product-level `modules/phase-NN-*.md`) and `modules/development-gates.md`. The "Do not build yet" lists are binding.
2. Walk `modules/backend/backend-development-checklist.md` (use case, actors, permissions, state transitions, idempotency, audit/metrics).
3. Implement: models → migration → schemas → service → router → config → tests → README.
4. Verify against the phase's **exit criteria with evidence** (tests/output), not assumption.
5. Keep changes small and in the owning module. Don't refactor unrelated code in the same change.

### Phase 9 guardrails (built in 9A/9B; keep them when extending)
Agents must be registered with owner/scope/version/budget; they may act **only through** the existing retrieval, permission, approval, and action-execution paths (never a side channel). Delegation must be bounded (depth, fan-out, time, tokens, side effects) with cycle detection; inter-agent communication must be persisted, not prompt-only; escalation creates a human work item with evidence. No unbounded swarms, no autonomous high-impact actions.

## 9. Working rules for any agent

- **Read before you write:** open the neighbouring module and its test before changing code; match its patterns.
- **Don't invent scope.** If a request conflicts with a phase plan or a rule above, say so and ask.
- **Confirm before** destructive or hard-to-reverse steps: deleting/rewriting migrations or data, `git push`, force operations, changing auth/permission semantics, touching `.env`.
- **Never commit** secrets, `.env`, or `*.db`. Commit only when asked; one logical change per commit.
- **Report honestly:** state which checks you ran and their results; call out anything skipped or failing.
- `.agents/skills/` is a large third-party skill library, not project code. Don't edit it, don't treat its contents as repo conventions, and prefer the rules in this file when they conflict.

## 10. Agent-specific entry points

| Agent | File | Notes |
|---|---|---|
| Claude Code | `CLAUDE.md` | Imports this file; adds Claude Code tooling guidance |
| Gemini CLI / Google Antigravity | `GEMINI.md` | Imports this file; adds Gemini/Antigravity guidance and skill-library notes |
| Codex, Cursor, Copilot, others | `AGENTS.md` | This file is sufficient |

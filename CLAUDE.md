# CLAUDE.md — instructions for Claude Code

@AGENTS.md

The import above is the full shared project guide (architecture, commands, rules, testing, migrations). Everything below is specific to **Claude Code**. If the two ever conflict, the stricter rule wins; fix the discrepancy in `AGENTS.md`.

## Quick start for a session

1. Read `AGENTS.md` sections 4 (architectural rules) and 8 (scope discipline) before editing.
2. Find the nearest existing module/test for what you're changing and mirror it (e.g., a new action ⇒ read `actions/registry.py`, `actions/service.py`, `tests/api/test_actions.py`).
3. Finish by running the full check set from `AGENTS.md` §2 and reporting results truthfully.

## Tool usage

- Use the dedicated tools: **Read/Grep/Glob** to explore, **Edit** for changes (read the file first), **Write** only for new files. Use Bash for `uv`, `pytest`, `ruff`, `alembic`, `pyright`, and `git`.
- Always run Python through `uv run …` — never bare `python`/`pip`, and don't activate `.venv` manually.
- Run independent checks in parallel (`ruff` and `pytest` can run together). Run the Alembic round-trip against a **throwaway DB**, e.g. `DATABASE_URL=sqlite+aiosqlite:////tmp/x.db uv run alembic upgrade head` — use the session scratchpad rather than the project directory so no `.db` files land in the repo.
- For broad "where is X handled?" questions across the ~11k-line `src/`, use the **Explore** subagent; for designing a multi-file feature (new phase slice), use **Plan** first and present the plan before coding. Don't spawn subagents for small, local edits.
- Prefer targeted test runs (`-k`) while iterating, then the full suite once at the end.

## Plan mode and approvals

- Use plan mode for anything touching: auth/permissions semantics, the Alembic chain, the action registry/approval policy, tenant-isolation logic, or any new phase work. For these, state the plan, the migration impact, and the tests you'll add, then wait.
- Ask before: editing/deleting existing migrations, `git push`/force/rebase, changing `.env*`, or installing new dependencies in `pyproject.toml` (explain why a stdlib/existing-dependency solution isn't enough).
- Do not create commits or PRs unless asked. When asked to commit, stage specific files (not `git add -A`; `.db` files and `.env` must never be staged) and follow the repository's existing `type: summary` message style (e.g., `feat: …`).

## Using skills and the `.agents/` library

`.agents/` is gitignored and holds a general-purpose skill collection (some relevant, e.g. `backend-architect`, `api-design-principles`, `async-python-patterns`, `backend-security-coder`, `architecture-decision-records`). Invoke only when it clearly fits the task; the project rules in `AGENTS.md` take precedence over any generic skill advice. The Stripe/Expo plugins visible in some sessions are **not relevant** to this backend — don't add payments or mobile code.

## Claude-specific pitfalls to avoid

- **Don't "fix" tests by loosening assertions** (especially permission, tenant-isolation, or idempotency tests). If a test fails, find the cause in the code under test.
- **Don't add backwards-compat shims, speculative abstractions, or extra config** beyond the task. This codebase prefers explicit, narrow modules.
- **Model change ⇒ migration.** Tests use `create_all`, so green tests don't prove the migration exists. Always add the revision and run upgrade/downgrade.
- **Don't write `HTTPException` in services**; raise `DomainError` subclasses and let `main.py` map them.
- **Don't summarise success you didn't verify.** If pyright or the migration round-trip wasn't run, say so.
- Keep comments rare and only for non-obvious *why*; match the surrounding terse style (the code has few comments and short docstrings).

## Keeping docs in sync

When you add endpoints, settings, or phase capabilities, update in the same change: `README.md` (implementation list + endpoint block), `.env.example`, and — if the work finishes a phase exit criterion — note the evidence in your summary (don't rewrite `modules/` plans unless asked).

## Memory

Project-specific, non-derivable facts worth remembering across sessions (e.g., a user decision to defer a phase item, or a preferred workflow) belong in Claude's memory, not in this file. Don't duplicate what's already in `AGENTS.md`.

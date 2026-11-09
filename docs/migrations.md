# Migration and deployment policy

Applies to every Alembic revision in `alembic/versions/`. `tests/test_migrations.py` enforces the
mechanical parts (one head, upgrade/downgrade/upgrade, models match migrations, revision ids fit
`VARCHAR(32)`), and CI runs the same round-trip.

## Expand / contract

A change that the running app and the new app must both survive ships in separate releases:

1. **Expand:** add nullable or defaulted columns, new tables and new indexes. Never rename or
   drop in this step.
2. **Backfill:** fill data in a separate, restartable step (a job or a migration that can be
   re-run), not inside the schema change.
3. **Switch:** deploy code that reads and writes the new shape. The old code must still work
   against the expanded schema.
4. **Contract:** in a later release, once nothing reads the old shape, drop it.

Never rename a column or table in place, tighten a constraint on live data in the same release
that starts writing it, or drop something in the release that stops using it.

## Checklist for every revision

- Chains from the current head; never edit a revision that has been committed or applied.
- Model change and revision land together (the parity test fails otherwise).
- Constraints and indexes are named explicitly.
- `downgrade` works and is honest about data loss (say so in a comment when narrowing a column).
- Revision id is at most 32 characters.
- SQLite needs `batch_alter_table` for alterations.

## Deploying

1. Take a backup (Postgres) or copy the database file (SQLite dev).
2. Run `alembic upgrade head` once, before rolling the app. Only one process runs it.
3. Roll the app and the worker. For one release both schemas must be tolerated (see expand).
4. Check `GET /observability/slos` and `GET /admin/usage` afterwards.

## Rolling back

1. Contain it first: switch off the affected capability (`docs/runbooks/kill-switches.md`) and
   stop the worker if jobs are misbehaving.
2. Roll the app back to the previous release. An expanded schema is compatible, so usually
   nothing more is needed.
3. Run `alembic downgrade -1` only if the revision is reversible and no data would be lost.
   Otherwise restore from the backup. Never downgrade past a revision whose data you still need.

## What is proven, and what is not

The migration tests and the Alembic round-trip (upgrade, `check`, downgrade, upgrade, and a
downgrade with long data stored) run on SQLite and, with `TEST_DATABASE_URL` set, on PostgreSQL
(a CI job runs them against `postgres:16`; locally they were run against 15.3). That covers type
parity between models and migrations and the 32-character revision id limit on a database that
enforces them.

Still not proven: zero-downtime behaviour on PostgreSQL (lock durations, online index builds,
long backfills), upgrades of a populated production-sized database, and deployment smoke tests.
The PostgreSQL CI job has not yet run on GitHub.

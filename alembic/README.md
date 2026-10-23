# Database migrations

The application uses Alembic for schema versioning. The Phase 1 migration creates the identity, membership, CRM, task, and audit tables.

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic downgrade base
```

The application can still create tables automatically for local development when `AUTO_CREATE_TABLES=true`. Production environments should set `AUTO_CREATE_TABLES=false` and apply migrations explicitly before starting the application.

def rotate(
    tenant_ids: list[str], start_offset: int | None, last_start: str | None
) -> tuple[list[str], str | None]:
    """Order tenants for this tick. With no explicit offset, start after the tenant that went
    first last time, so rotation stays fair even though the busy set changes between ticks.
    Returns the order and the new "first tenant" marker."""
    if not tenant_ids:
        return tenant_ids, last_start
    if start_offset is not None:
        pivot = start_offset % len(tenant_ids)
    else:
        pivot = next(
            (
                index
                for index, name in enumerate(tenant_ids)
                if last_start is None or name > last_start
            ),
            0,
        )
        last_start = tenant_ids[pivot]
    return tenant_ids[pivot:] + tenant_ids[:pivot], last_start

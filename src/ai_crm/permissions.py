from enum import StrEnum


class Permission(StrEnum):
    CONTACTS_READ = "contacts:read"
    CONTACTS_CREATE = "contacts:create"
    CONTACTS_UPDATE = "contacts:update"
    COMPANIES_READ = "companies:read"
    COMPANIES_CREATE = "companies:create"
    COMPANIES_UPDATE = "companies:update"
    OPPORTUNITIES_READ = "opportunities:read"
    OPPORTUNITIES_CREATE = "opportunities:create"
    OPPORTUNITIES_UPDATE = "opportunities:update"
    ACTIVITIES_READ = "activities:read"
    ACTIVITIES_CREATE = "activities:create"
    TASKS_READ = "tasks:read"
    TASKS_CREATE = "tasks:create"
    TASKS_UPDATE = "tasks:update"
    INTEGRATIONS_READ = "integrations:read"
    INTEGRATIONS_MANAGE = "integrations:manage"
    INTEGRATIONS_SYNC = "integrations:sync"
    INTEGRATIONS_WRITE = "integrations:write"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "manager": frozenset(Permission),
    "member": frozenset(Permission),
    "viewer": frozenset(
        {
            Permission.CONTACTS_READ,
            Permission.COMPANIES_READ,
            Permission.OPPORTUNITIES_READ,
            Permission.ACTIVITIES_READ,
            Permission.TASKS_READ,
            Permission.INTEGRATIONS_READ,
        }
    ),
}


def permissions_for_role(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())

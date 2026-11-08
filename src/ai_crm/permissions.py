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
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_MANAGE = "knowledge:manage"
    KNOWLEDGE_CONTEXT = "knowledge:context"
    KNOWLEDGE_SENSITIVE = "knowledge:sensitive"
    WORK_READ = "work:read"
    WORK_MANAGE = "work:manage"
    JOBS_READ = "jobs:read"
    JOBS_MANAGE = "jobs:manage"
    WORKFLOWS_READ = "workflows:read"
    WORKFLOWS_MANAGE = "workflows:manage"
    AI_READ = "ai:read"
    AI_USE = "ai:use"
    AI_FEEDBACK = "ai:feedback"
    ACTIONS_READ = "actions:read"
    ACTIONS_PROPOSE = "actions:propose"
    ACTIONS_APPROVE = "actions:approve"
    ACTIONS_EXECUTE = "actions:execute"
    ACTIONS_RECOVER = "actions:recover"
    OBSERVABILITY_READ = "observability:read"
    OBSERVABILITY_MANAGE = "observability:manage"
    ADMIN_MEMBERS_READ = "admin:members:read"
    ADMIN_MEMBERS_MANAGE = "admin:members:manage"
    ADMIN_USAGE_READ = "admin:usage:read"
    ADMIN_FLAGS_READ = "admin:flags:read"
    ADMIN_FLAGS_MANAGE = "admin:flags:manage"
    AGENTS_READ = "agents:read"
    AGENTS_RUN = "agents:run"
    AGENTS_MANAGE = "agents:manage"
    AGENTS_EVALUATE = "agents:evaluate"


_VIEWER_PERMISSIONS = frozenset(
    {
        Permission.CONTACTS_READ,
        Permission.COMPANIES_READ,
        Permission.OPPORTUNITIES_READ,
        Permission.ACTIVITIES_READ,
        Permission.TASKS_READ,
        Permission.INTEGRATIONS_READ,
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_CONTEXT,
        Permission.WORK_READ,
        Permission.JOBS_READ,
        Permission.WORKFLOWS_READ,
        Permission.AI_READ,
        Permission.AI_USE,
        Permission.ACTIONS_READ,
        Permission.OBSERVABILITY_READ,
        Permission.AGENTS_READ,
    }
)

_MEMBER_PERMISSIONS = _VIEWER_PERMISSIONS | {
    Permission.CONTACTS_CREATE,
    Permission.CONTACTS_UPDATE,
    Permission.COMPANIES_CREATE,
    Permission.COMPANIES_UPDATE,
    Permission.OPPORTUNITIES_CREATE,
    Permission.OPPORTUNITIES_UPDATE,
    Permission.ACTIVITIES_CREATE,
    Permission.TASKS_CREATE,
    Permission.TASKS_UPDATE,
    Permission.INTEGRATIONS_SYNC,
    Permission.KNOWLEDGE_MANAGE,
    Permission.WORK_MANAGE,
    Permission.JOBS_MANAGE,
    Permission.WORKFLOWS_MANAGE,
    Permission.AI_FEEDBACK,
    Permission.ACTIONS_PROPOSE,
    Permission.ACTIONS_EXECUTE,
    Permission.AGENTS_RUN,
}

_MANAGER_PERMISSIONS = _MEMBER_PERMISSIONS | {
    Permission.KNOWLEDGE_SENSITIVE,
    Permission.INTEGRATIONS_WRITE,
    Permission.ACTIONS_APPROVE,
    Permission.ACTIONS_RECOVER,
    Permission.OBSERVABILITY_MANAGE,
    Permission.ADMIN_MEMBERS_READ,
    Permission.ADMIN_FLAGS_READ,
    Permission.ADMIN_USAGE_READ,
}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "admin": frozenset(Permission),
    "manager": _MANAGER_PERMISSIONS,
    "member": _MEMBER_PERMISSIONS,
    "viewer": _VIEWER_PERMISSIONS,
}


def permissions_for_role(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())

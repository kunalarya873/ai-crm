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
            Permission.KNOWLEDGE_READ,
            Permission.KNOWLEDGE_CONTEXT,
            Permission.WORK_READ,
            Permission.JOBS_READ,
            Permission.WORKFLOWS_READ,
            Permission.AI_READ,
            Permission.AI_USE,
            Permission.ACTIONS_READ,
            Permission.OBSERVABILITY_READ,
        }
    ),
}


def permissions_for_role(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())

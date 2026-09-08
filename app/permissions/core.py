from enum import StrEnum
from fastapi import HTTPException


class Permission(StrEnum):
    READ_ALL = "read_all"
    MANAGE_FINANCE = "manage_finance"
    MANAGE_WAREHOUSE = "manage_warehouse"
    MANAGE_CRM = "manage_crm"
    MANAGE_PENALTIES = "manage_penalties"
    EXPORT = "export"
    SHIFT = "shift"
    HALL = "hall"
    GUESTS = "guests"
    SALES = "sales"
    WAREHOUSE = "warehouse"
    TASKS = "tasks"
    OWN_PENALTIES = "own_penalties"
    AUDIENCE = "audience"
    SEGMENTS = "segments"
    CAMPAIGNS = "campaigns"
    ACTIVITIES = "activities"
    RESULTS = "results"
    OWN_PROFILE = "own_profile"
    OWN_BALANCE = "own_balance"
    OWN_HISTORY = "own_history"


ROLE_PERMISSIONS = {
    "owner": frozenset(Permission),
    "admin": frozenset({Permission.SHIFT, Permission.HALL, Permission.GUESTS, Permission.SALES, Permission.WAREHOUSE, Permission.TASKS, Permission.OWN_PENALTIES, Permission.EXPORT}),
    "smm": frozenset({Permission.AUDIENCE, Permission.SEGMENTS, Permission.CAMPAIGNS, Permission.ACTIVITIES, Permission.RESULTS, Permission.EXPORT}),
    "guest": frozenset({Permission.OWN_PROFILE, Permission.OWN_BALANCE, Permission.OWN_HISTORY}),
}


def has_permission(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(str(role).lower(), frozenset())


def require_permission(role: str, permission: Permission) -> None:
    if not has_permission(role, permission):
        raise HTTPException(403, f"Permission required: {permission.value}")

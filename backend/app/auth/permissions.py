"""Map JWT claims to an authenticated principal and check space permissions.

Claims (API Spec §3):
  - roles:  ["reader" | "editor" | "admin"]      (global default permissions)
  - scopes: ["space:<slug>:read|write|admin"]    (explicit per-space ACLs)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Permission(IntEnum):
    READ = 1
    WRITE = 2
    ADMIN = 3


_ROLE_PERMISSION = {
    "reader": Permission.READ,
    "editor": Permission.WRITE,
    "admin": Permission.ADMIN,
}
_PERMISSION_NAME = {"read": Permission.READ, "write": Permission.WRITE, "admin": Permission.ADMIN}


@dataclass
class Principal:
    sub: str
    email: str | None
    locale: str | None
    roles: list[str] = field(default_factory=list)
    # Highest global permission granted by roles (None if no recognized role).
    global_permission: Permission | None = None
    # Per-space overrides: slug -> highest permission.
    space_permissions: dict[str, Permission] = field(default_factory=dict)

    def permission_for(self, space_slug: str) -> Permission | None:
        explicit = self.space_permissions.get(space_slug)
        if explicit is not None and self.global_permission is not None:
            return max(explicit, self.global_permission)
        return explicit or self.global_permission

    def can(self, space_slug: str, required: Permission) -> bool:
        granted = self.permission_for(space_slug)
        return granted is not None and granted >= required


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    roles = [r for r in claims.get("roles", []) if isinstance(r, str)]
    global_perm: Permission | None = None
    for role in roles:
        perm = _ROLE_PERMISSION.get(role)
        if perm is not None and (global_perm is None or perm > global_perm):
            global_perm = perm

    space_perms: dict[str, Permission] = {}
    for scope in claims.get("scopes", []):
        # Format: "space:<slug>:<permission>"
        parts = scope.split(":") if isinstance(scope, str) else []
        if len(parts) == 3 and parts[0] == "space":
            _, slug, perm_name = parts
            perm = _PERMISSION_NAME.get(perm_name)
            if perm is not None and (slug not in space_perms or perm > space_perms[slug]):
                space_perms[slug] = perm

    return Principal(
        sub=claims["sub"],
        email=claims.get("email"),
        locale=claims.get("locale"),
        roles=roles,
        global_permission=global_perm,
        space_permissions=space_perms,
    )

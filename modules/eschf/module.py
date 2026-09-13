"""Declarative local ESCHF API/RBAC registration, without background dispatch."""

from core.runtime.contract import ModuleContract, Role
from core.runtime.core import Core
from modules.eschf.repository import PERMISSIONS
from modules.eschf.routes import router


class EschfModule(ModuleContract):
    name = "eschf"
    api_prefix = "/eschf"

    def register(self, core: Core) -> None:
        core.include_router(router, prefix=self.api_prefix)
        core.declare_permissions(list(PERMISSIONS))
        # Declarations do not assign a user or broaden an existing business role.
        core.declare_role(
            Role(
                "eschf_accountant",
                tuple(f"eschf.{p}" for p in ("read", "prepare", "approve", "queue", "reconcile")),
            )
        )
        core.declare_role(Role("eschf_auditor", ("eschf.read",)))
        core.declare_role(Role("eschf_worker", ("eschf.read", "eschf.worker", "eschf.reconcile")))


def get_module() -> ModuleContract:
    return EschfModule()

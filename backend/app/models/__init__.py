"""Importing this package registers every table on SQLModel.metadata."""

from app.models.architecture import (  # noqa: F401
    ADRComponentLink,
    ArchitectureComponent,
    ArchitectureDecision,
)
from app.models.integration import Connection, ExternalRef  # noqa: F401
from app.models.project import Dependency, Milestone, Project, Task  # noqa: F401
from app.models.team import Allocation, Engineer, Role  # noqa: F401
from app.models.user import User  # noqa: F401

__all__ = [
    "ADRComponentLink",
    "Allocation",
    "ArchitectureComponent",
    "ArchitectureDecision",
    "Connection",
    "Dependency",
    "Engineer",
    "ExternalRef",
    "Milestone",
    "Project",
    "Role",
    "Task",
    "User",
]

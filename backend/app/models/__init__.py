"""Importing this package registers every table on SQLModel.metadata."""

from app.models.architecture import (
    ADRComponentLink,
    ArchitectureComponent,
    ArchitectureDecision,
)
from app.models.integration import Connection, ExternalRef
from app.models.project import Dependency, Milestone, Project, Task
from app.models.team import Allocation, Engineer, Role
from app.models.user import User

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

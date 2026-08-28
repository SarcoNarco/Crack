"""Offline-only registration for Crack's single supported local target shape."""

from .inspection import ImportPlan, TargetImportError, inspect_target
from .registry import Registration, register_approved

__all__ = [
    "ImportPlan",
    "Registration",
    "TargetImportError",
    "inspect_target",
    "register_approved",
]

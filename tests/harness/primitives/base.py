"""Base types for test primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PrimitiveResult:
    """Result from a test primitive.

    Provides a consistent structure for test outcomes across all primitives,
    enabling composition and detailed reporting.
    """

    success: bool
    name: str
    node: str
    duration: float = 0.0
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __bool__(self) -> bool:
        """Allow using result directly in assertions."""
        return self.success

    def __str__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        base = f"[{status}] {self.name} on {self.node}"
        if self.message:
            base += f": {self.message}"
        if self.error:
            base += f" (error: {self.error})"
        return base

    def as_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "name": self.name,
            "node": self.node,
            "duration": self.duration,
            "message": self.message,
            "data": self.data,
            "error": self.error,
        }

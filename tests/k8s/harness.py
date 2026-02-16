"""K8s test orchestration harness for styrened containerized testing.

This module re-exports from the unified harness package for backward compatibility.
New code should import directly from tests.harness.k8s.
"""

from __future__ import annotations

# Re-export from unified harness for backward compatibility
from tests.harness.base import CommandResult as ExecResult
from tests.harness.k8s import K8sHarness as K8sTestHarness

__all__ = ["K8sTestHarness", "ExecResult"]

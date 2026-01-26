"""Styrened - Headless Styrene daemon for edge deployments.

Lightweight daemon built on styrene-core for running Styrene services
without the TUI. Optimized for resource-constrained devices and NixOS
deployments.
"""

__version__ = "0.1.0"

from styrened.daemon import StyreneDaemon, main

__all__ = ["StyreneDaemon", "main", "__version__"]

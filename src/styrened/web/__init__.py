"""Styrened web UI — mesh topology explorer.

Embeds a FastAPI app serving both JSON API endpoints and a static
single-page frontend for visualizing the Reticulum mesh graph.
"""
from __future__ import annotations

from styrened.web.app import create_app

__all__ = ["create_app"]

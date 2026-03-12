"""Helper module for NomadNet executable page scripts on the hub.

NomadNet runs executable ``.mu`` scripts as subprocesses, passing
``remote_identity`` in environment variables. This module provides
a helper that:

1. Reads environment variables set by NomadNet
2. Calls a user-provided generator function
3. Wraps the output with :func:`~styrened.pages.builder.build_page`
4. Prints the dual-layer page to stdout

Usage in an executable ``.mu`` script::

    #!/usr/bin/env python3
    from styrened.pages.hub_bridge import serve_dynamic_page

    def generate(remote_identity: str, form_data: dict) -> tuple[str, dict]:
        # ... query IPC, build micron ...
        return micron, data

    if __name__ == "__main__":
        serve_dynamic_page(generate, page_type="fleet")
"""
from __future__ import annotations


import os
import sys
from collections.abc import Callable
from typing import Any

from styrened.pages.builder import build_page


def get_remote_identity() -> str:
    """Read remote identity hash from NomadNet environment.

    NomadNet sets ``remote_identity`` in the subprocess environment.

    Returns:
        Hex identity hash string, or empty string if not available.
    """
    return os.environ.get("remote_identity", "")


def get_form_data() -> dict[str, str]:
    """Read form submission data from NomadNet environment.

    NomadNet passes form data as ``field_<name>`` environment variables.

    Returns:
        Dictionary of field name → value pairs.
    """
    result: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith("field_"):
            field_name = key[6:]  # Strip "field_" prefix
            result[field_name] = value
    return result


# Type alias for generator functions
PageGenerator = Callable[
    [str, dict[str, str]],  # remote_identity, form_data
    tuple[str, dict[str, Any]],  # (micron_content, structured_data)
]


def serve_dynamic_page(
    generator: PageGenerator,
    page_type: str,
    encoding: str = "b85",
    capabilities: list[str] | None = None,
    cache_ttl: int | None = None,
) -> None:
    """Entry point for executable .mu page scripts.

    Reads NomadNet environment, calls the generator, wraps output with
    :func:`build_page`, and prints to stdout.

    Args:
        generator: Function returning ``(micron_content, structured_data)``.
        page_type: Page type for Styrene metadata.
        encoding: Block encoding (``"b85"`` or ``"json"``).
        capabilities: Node capabilities to advertise.
        cache_ttl: NomadNet cache TTL in seconds.
    """
    remote_identity = get_remote_identity()
    form_data = get_form_data()

    try:
        micron, data = generator(remote_identity, form_data)
    except Exception as e:
        # Generate error page
        micron = f">Error\nFailed to generate page: {e}\n"
        data = {"error": str(e)}

    page = build_page(
        micron=micron,
        data=data,
        page_type=page_type,
        encoding=encoding,
        capabilities=capabilities,
        cache_ttl=cache_ttl,
    )

    sys.stdout.write(page)
    sys.stdout.flush()

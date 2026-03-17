"""Canonical editable configuration draft state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from styrened.ui_state.base import LoadState, RefreshMeta


class ConfigSaveState(StrEnum):
    """Save lifecycle for an editable config draft."""

    IDLE = "idle"
    SAVING = "saving"
    SAVED = "saved"
    ERROR = "error"


@dataclass(frozen=True)
class ConfigValidationIssue:
    """Validation issue attached to a config field path."""

    field_path: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class ConfigDraftState:
    """Canonical editable configuration state.

    Keeps the persisted snapshot distinct from the editable snapshot so UI layers
    can render dirty state, validation issues, and save/reset affordances without
    mutating raw dicts in-place.
    """

    persisted: dict[str, Any]
    editable: dict[str, Any]
    dirty_fields: tuple[str, ...] = ()
    validation_issues: tuple[ConfigValidationIssue, ...] = ()
    is_dirty: bool = False
    save_state: ConfigSaveState = ConfigSaveState.IDLE
    save_error: str | None = None
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class ConfigDraftInputs:
    """Authoritative inputs for config draft state construction."""

    persisted: dict[str, Any] | None = None
    editable: dict[str, Any] | None = None
    validation_errors: dict[str, str] | None = None
    saving: bool = False
    save_succeeded: bool = False
    save_error: str | None = None
    now: float | None = None


def _normalize_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


def _collect_dirty_fields(
    persisted: dict[str, Any],
    editable: dict[str, Any],
    prefix: str = "",
) -> list[str]:
    dirty: list[str] = []
    keys = set(persisted) | set(editable)
    for key in sorted(keys):
        field_path = f"{prefix}.{key}" if prefix else key
        left = persisted.get(key)
        right = editable.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            dirty.extend(_collect_dirty_fields(left, right, field_path))
            continue
        if left != right:
            dirty.append(field_path)
    return dirty


def build_config_draft_state(inputs: ConfigDraftInputs) -> ConfigDraftState:
    """Build canonical editable configuration state."""
    import time

    persisted = _normalize_mapping(inputs.persisted)
    editable = _normalize_mapping(inputs.editable) if inputs.editable is not None else dict(persisted)
    dirty_fields = tuple(_collect_dirty_fields(persisted, editable))

    issues = tuple(
        ConfigValidationIssue(field_path=field, message=message)
        for field, message in sorted((inputs.validation_errors or {}).items())
    )

    if inputs.save_error:
        save_state = ConfigSaveState.ERROR
    elif inputs.saving:
        save_state = ConfigSaveState.SAVING
    elif inputs.save_succeeded:
        save_state = ConfigSaveState.SAVED
    else:
        save_state = ConfigSaveState.IDLE

    now = inputs.now if inputs.now is not None else time.time()

    return ConfigDraftState(
        persisted=persisted,
        editable=editable,
        dirty_fields=dirty_fields,
        validation_issues=issues,
        is_dirty=bool(dirty_fields),
        save_state=save_state,
        save_error=inputs.save_error,
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=now),
    )

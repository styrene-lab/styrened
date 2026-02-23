"""Pydantic request models for the styrened REST API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SendChatRequest(BaseModel):
    """Request body for sending a chat message."""

    content: str = Field(..., min_length=1, max_length=65536)
    title: str | None = Field(None, max_length=256)
    delivery_method: str = Field("auto", pattern=r"^(auto|direct|propagated)$")
    reply_to_hash: str | None = None


class SetContactRequest(BaseModel):
    """Request body for setting a contact alias."""

    alias: str = Field(..., min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=500)


class ExecCommandRequest(BaseModel):
    """Request body for remote command execution."""

    command: str = Field(..., min_length=1)
    args: list[str] = Field(default_factory=list)
    timeout: float = Field(60.0, ge=1.0, le=300.0)


class ConfigUpdateRequest(BaseModel):
    """Partial config update. Only provided sections/fields are changed."""

    profile: str | None = None
    reticulum: dict[str, Any] | None = None
    identity: dict[str, Any] | None = None
    rpc: dict[str, Any] | None = None
    discovery: dict[str, Any] | None = None
    chat: dict[str, Any] | None = None
    api: dict[str, Any] | None = None
    ipc: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    lxmf: dict[str, Any] | None = None
    terminal: dict[str, Any] | None = None


class AutoReplyToggleRequest(BaseModel):
    """Request body for setting auto-reply mode."""

    mode: str = Field(..., pattern=r"^(disabled|template|chatbot)$")
    message: str | None = Field(None, max_length=1024)


class RebootRequest(BaseModel):
    """Request body for remote device reboot."""

    delay: int = Field(0, ge=0, le=3600)


class FleetConfigUpdateRequest(BaseModel):
    """Request body for remote config update."""

    config_updates: dict[str, Any]
    timeout: float = Field(10.0, ge=1.0, le=60.0)

"""Pydantic request models for the styrened REST API."""

from __future__ import annotations

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

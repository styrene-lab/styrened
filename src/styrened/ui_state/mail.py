"""Canonical aggregate state for asynchronous Mail."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from styrened.ui_state.base import LoadState, RefreshMeta


class ConversationScopeKind(str, Enum):
    """Canonical async discussion scopes."""

    DIRECT = "direct"
    GROUP = "group"
    FORUM = "forum"


@dataclass(frozen=True)
class MailTransportMeta:
    """Transport metadata attached to messages or threads."""

    transport: str
    via_bridge: bool = False
    bridge_kind: str | None = None
    fallback_used: bool = False


class DeliveryPathClass(str, Enum):
    """Relative quality/cost classification for a route."""

    HIGH = "high"
    CONSTRAINED = "constrained"
    STORE_AND_FORWARD = "store-and-forward"
    UNKNOWN = "unknown"


class MediaFrictionLevel(str, Enum):
    """How cautious the UI should be with expensive media actions."""

    NONE = "none"
    CONFIRM = "confirm"
    AVOID = "avoid"


class GroupThreadFeatureTier(str, Enum):
    """Local feature/storage tier for group-thread behavior."""

    MINIMAL = "minimal"
    BALANCED = "balanced"
    FULL = "full"


@dataclass(frozen=True)
class GroupParticipantRecord:
    """Canonical participant reachability and delivery profile for a room."""

    identity: str
    display_name: str | None = None
    highest_available_interface: str | None = None
    fallback_interfaces: tuple[str, ...] = ()
    delivery_path_class: DeliveryPathClass = DeliveryPathClass.UNKNOWN
    media_friction: MediaFrictionLevel = MediaFrictionLevel.NONE
    requires_media_confirmation: bool = False


@dataclass(frozen=True)
class GroupThreadPolicy:
    """Local degradation/retention policy for a group thread."""

    feature_tier: GroupThreadFeatureTier = GroupThreadFeatureTier.BALANCED
    bounded_retention: bool = False
    auto_media_fetch: bool = True
    metadata_first_sync: bool = False
    background_catchup: bool = True


@dataclass(frozen=True)
class GroupThreadMeta:
    """Private room metadata for group threads."""

    room_id: str
    room_name: str | None = None
    epoch_id: str | None = None
    member_count: int | None = None
    participants: tuple[GroupParticipantRecord, ...] = ()
    policy: GroupThreadPolicy = field(default_factory=GroupThreadPolicy)


@dataclass(frozen=True)
class ForumThreadMeta:
    """Topic metadata for forum/page-linked discussions."""

    topic_id: str
    topic_title: str | None = None
    page_ref: str | None = None


@dataclass(frozen=True)
class MailMessageRecord:
    """Canonical async message record."""

    message_id: str
    thread_id: str
    sender_identity: str | None = None
    preview: str = ""
    timestamp: float | None = None
    outgoing: bool = False
    transport: MailTransportMeta | None = None


@dataclass(frozen=True)
class MailThreadRecord:
    """Canonical async thread summary."""

    thread_id: str
    scope_kind: ConversationScopeKind
    display_name: str
    participant_identity: str | None = None
    unread_count: int = 0
    latest_message: MailMessageRecord | None = None
    transports: tuple[MailTransportMeta, ...] = ()
    group: GroupThreadMeta | None = None
    forum: ForumThreadMeta | None = None


@dataclass(frozen=True)
class MailIndexState:
    """Canonical async inbox/thread index."""

    threads: tuple[MailThreadRecord, ...]
    by_thread_id: dict[str, MailThreadRecord]
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class MailIndexInputs:
    """Authoritative inputs for building a mail index."""

    threads: tuple[object, ...]
    now: float | None = None


_SCOPE_MAP = {
    "direct": ConversationScopeKind.DIRECT,
    "group": ConversationScopeKind.GROUP,
    "forum": ConversationScopeKind.FORUM,
}

_PATH_CLASS_MAP = {
    "high": DeliveryPathClass.HIGH,
    "constrained": DeliveryPathClass.CONSTRAINED,
    "store-and-forward": DeliveryPathClass.STORE_AND_FORWARD,
    "store_and_forward": DeliveryPathClass.STORE_AND_FORWARD,
    "unknown": DeliveryPathClass.UNKNOWN,
}

_MEDIA_FRICTION_MAP = {
    "none": MediaFrictionLevel.NONE,
    "confirm": MediaFrictionLevel.CONFIRM,
    "avoid": MediaFrictionLevel.AVOID,
}

_FEATURE_TIER_MAP = {
    "minimal": GroupThreadFeatureTier.MINIMAL,
    "balanced": GroupThreadFeatureTier.BALANCED,
    "full": GroupThreadFeatureTier.FULL,
}


def _safe_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_int(value: object, *, minimum: int | None = None, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if minimum is not None:
        return max(minimum, parsed)
    return parsed


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return None


def _coerce_scope(raw: object) -> ConversationScopeKind:
    value = str(
        getattr(raw, "scope_kind", None)
        or getattr(raw, "thread_scope", None)
        or getattr(raw, "scope", None)
        or "direct"
    ).lower()
    return _SCOPE_MAP.get(value, ConversationScopeKind.DIRECT)


def _coerce_path_class(value: object) -> DeliveryPathClass:
    normalized = (_safe_text(value) or "unknown").lower()
    return _PATH_CLASS_MAP.get(normalized, DeliveryPathClass.UNKNOWN)


def _coerce_media_friction(value: object, *, requires_confirmation: bool = False) -> MediaFrictionLevel:
    normalized = (_safe_text(value) or "").lower()
    if normalized in _MEDIA_FRICTION_MAP:
        return _MEDIA_FRICTION_MAP[normalized]
    if requires_confirmation:
        return MediaFrictionLevel.CONFIRM
    return MediaFrictionLevel.NONE


def _coerce_feature_tier(value: object) -> GroupThreadFeatureTier:
    normalized = (_safe_text(value) or "balanced").lower()
    return _FEATURE_TIER_MAP.get(normalized, GroupThreadFeatureTier.BALANCED)


def _transport_meta(raw: object) -> MailTransportMeta | None:
    transport = getattr(raw, "transport", None) or getattr(raw, "transport_kind", None)
    if transport is None and isinstance(raw, dict):
        transport = raw.get("transport") or raw.get("transport_kind")
    if not transport:
        return None
    if isinstance(raw, dict):
        via_bridge = bool(raw.get("via_bridge", False))
        bridge_kind = raw.get("bridge_kind")
        fallback_used = bool(raw.get("fallback_used", False))
    else:
        via_bridge = bool(getattr(raw, "via_bridge", False))
        bridge_kind = getattr(raw, "bridge_kind", None)
        fallback_used = bool(getattr(raw, "fallback_used", False))
    safe_transport = _safe_text(transport)
    if not safe_transport:
        return None
    return MailTransportMeta(
        transport=safe_transport,
        via_bridge=via_bridge,
        bridge_kind=_safe_text(bridge_kind),
        fallback_used=fallback_used,
    )


def _message_record(thread_id: str, raw: object) -> MailMessageRecord | None:
    if isinstance(raw, dict):
        message_id = str(raw.get("message_id") or raw.get("id") or "")
        preview = str(raw.get("last_message_preview") or raw.get("preview") or "")
        timestamp = raw.get("last_message_time") or raw.get("timestamp")
        sender_identity = raw.get("sender_identity") or raw.get("peer_hash")
        outgoing = bool(raw.get("is_outgoing", False))
    else:
        message_id = str(getattr(raw, "message_id", None) or getattr(raw, "id", None) or "")
        preview = str(getattr(raw, "last_message_preview", None) or getattr(raw, "preview", None) or "")
        timestamp = getattr(raw, "last_message_time", None) or getattr(raw, "timestamp", None)
        sender_identity = getattr(raw, "sender_identity", None) or getattr(raw, "peer_hash", None)
        outgoing = bool(getattr(raw, "is_outgoing", False))
    if not message_id:
        message_id = f"{thread_id}:latest"
    return MailMessageRecord(
        message_id=message_id,
        thread_id=thread_id,
        sender_identity=_safe_text(sender_identity),
        preview=preview,
        timestamp=_safe_float(timestamp),
        outgoing=outgoing,
        transport=_transport_meta(raw),
    )


def _transports(raw: object, latest: MailMessageRecord | None) -> tuple[MailTransportMeta, ...]:
    entries: list[MailTransportMeta] = []
    if latest and latest.transport:
        entries.append(latest.transport)
    raw_list = None
    if isinstance(raw, dict):
        raw_list = raw.get("transports")
    else:
        raw_list = getattr(raw, "transports", None)
    if isinstance(raw_list, (list, tuple)):
        for item in raw_list:
            if isinstance(item, MailTransportMeta):
                entries.append(item)
            elif isinstance(item, dict):
                transport = item.get("transport") or item.get("transport_kind")
                if transport:
                    safe_transport = _safe_text(transport)
                    if safe_transport:
                        entries.append(
                            MailTransportMeta(
                                transport=safe_transport,
                                via_bridge=bool(item.get("via_bridge", False)),
                                bridge_kind=_safe_text(item.get("bridge_kind")),
                                fallback_used=bool(item.get("fallback_used", False)),
                            )
                        )
    dedup: dict[tuple[str, bool, str | None, bool], MailTransportMeta] = {}
    for entry in entries:
        dedup[(entry.transport, entry.via_bridge, entry.bridge_kind, entry.fallback_used)] = entry
    return tuple(dedup.values())


def _group_participants(raw: object) -> tuple[GroupParticipantRecord, ...]:
    raw_participants = raw.get("participants") if isinstance(raw, dict) else getattr(raw, "participants", None)
    if not isinstance(raw_participants, (list, tuple)):
        return ()
    participants: list[GroupParticipantRecord] = []
    for item in raw_participants:
        if not isinstance(item, dict):
            continue
        identity = _safe_text(item.get("identity") or item.get("identity_hash") or item.get("peer_identity"))
        if not identity:
            continue
        requires_confirmation = bool(item.get("requires_media_confirmation", False))
        fallback = item.get("fallback_interfaces")
        participants.append(
            GroupParticipantRecord(
                identity=identity,
                display_name=_safe_text(item.get("display_name") or item.get("name")),
                highest_available_interface=_safe_text(item.get("highest_available_interface") or item.get("best_interface")),
                fallback_interfaces=tuple(
                    text for text in (_safe_text(entry) for entry in (fallback if isinstance(fallback, (list, tuple)) else ())) if text
                ),
                delivery_path_class=_coerce_path_class(item.get("delivery_path_class") or item.get("path_class")),
                media_friction=_coerce_media_friction(item.get("media_friction"), requires_confirmation=requires_confirmation),
                requires_media_confirmation=requires_confirmation,
            )
        )
    return tuple(participants)


def _group_policy(raw: object) -> GroupThreadPolicy:
    data = raw.get("group_policy") if isinstance(raw, dict) else getattr(raw, "group_policy", None)
    if not isinstance(data, dict):
        data = raw.get("policy") if isinstance(raw, dict) else getattr(raw, "policy", None)
    if not isinstance(data, dict):
        data = {}
    return GroupThreadPolicy(
        feature_tier=_coerce_feature_tier(data.get("feature_tier")),
        bounded_retention=bool(data.get("bounded_retention", False)),
        auto_media_fetch=bool(data.get("auto_media_fetch", True)),
        metadata_first_sync=bool(data.get("metadata_first_sync", False)),
        background_catchup=bool(data.get("background_catchup", True)),
    )


def _group_meta(raw: object) -> GroupThreadMeta | None:
    data = raw.get("group") if isinstance(raw, dict) else getattr(raw, "group", None)
    if isinstance(raw, dict):
        nested = data if isinstance(data, dict) else {}
        room_id = raw.get("room_id") or nested.get("room_id")
        if not room_id:
            return None
        room_name = raw.get("room_name") or nested.get("room_name")
        epoch_id = raw.get("epoch_id") or nested.get("epoch_id")
        member_count = raw.get("member_count") if raw.get("member_count") is not None else nested.get("member_count")
    else:
        room_id = getattr(raw, "room_id", None) or (getattr(data, "room_id", None) if data else None)
        if not room_id:
            return None
        room_name = getattr(raw, "room_name", None) or (getattr(data, "room_name", None) if data else None)
        epoch_id = getattr(raw, "epoch_id", None) or (getattr(data, "epoch_id", None) if data else None)
        member_count = getattr(raw, "member_count", None)
        if member_count is None and data is not None:
            member_count = getattr(data, "member_count", None)
    safe_room_id = _safe_text(room_id)
    if not safe_room_id:
        return None
    participants = _group_participants(data if isinstance(data, dict) else raw)
    resolved_member_count = _safe_int(member_count, minimum=0, default=0) if member_count is not None else None
    if resolved_member_count is None and participants:
        resolved_member_count = len(participants)
    return GroupThreadMeta(
        room_id=safe_room_id,
        room_name=_safe_text(room_name),
        epoch_id=_safe_text(epoch_id),
        member_count=resolved_member_count,
        participants=participants,
        policy=_group_policy(data if isinstance(data, dict) else raw),
    )


def _forum_meta(raw: object) -> ForumThreadMeta | None:
    data = raw.get("forum") if isinstance(raw, dict) else getattr(raw, "forum", None)
    if isinstance(raw, dict):
        nested = data if isinstance(data, dict) else {}
        topic_id = raw.get("topic_id") or nested.get("topic_id")
        if not topic_id:
            return None
        topic_title = raw.get("topic_title") or nested.get("topic_title")
        page_ref = raw.get("page_ref") or nested.get("page_ref")
    else:
        topic_id = getattr(raw, "topic_id", None) or (getattr(data, "topic_id", None) if data else None)
        if not topic_id:
            return None
        topic_title = getattr(raw, "topic_title", None) or (getattr(data, "topic_title", None) if data else None)
        page_ref = getattr(raw, "page_ref", None) or (getattr(data, "page_ref", None) if data else None)
    safe_topic_id = _safe_text(topic_id)
    if not safe_topic_id:
        return None
    return ForumThreadMeta(
        topic_id=safe_topic_id,
        topic_title=_safe_text(topic_title),
        page_ref=_safe_text(page_ref),
    )


def build_mail_index(inputs: MailIndexInputs) -> MailIndexState:
    """Build a canonical async inbox/thread index."""
    now = inputs.now if inputs.now is not None else time.time()
    threads: list[MailThreadRecord] = []
    for raw in inputs.threads:
        if isinstance(raw, dict):
            scope = _SCOPE_MAP.get(str(raw.get("scope_kind") or raw.get("thread_scope") or raw.get("scope") or "direct").lower(), ConversationScopeKind.DIRECT)
            participant_identity = raw.get("peer_identity") or raw.get("peer_hash")
            room_id = raw.get("room_id")
            topic_id = raw.get("topic_id")
            thread_id = _safe_text(raw.get("thread_id") or room_id or topic_id or participant_identity or raw.get("id") or "") or ""
            display_name = _safe_text(raw.get("display_name") or raw.get("alias") or raw.get("room_name") or raw.get("topic_title") or participant_identity or thread_id) or thread_id
            unread_count = _safe_int(raw.get("unread_count", 0) or 0, minimum=0)
        else:
            scope = _coerce_scope(raw)
            participant_identity = getattr(raw, "peer_identity", None) or getattr(raw, "peer_hash", None)
            room_id = getattr(raw, "room_id", None)
            topic_id = getattr(raw, "topic_id", None)
            thread_id = _safe_text(getattr(raw, "thread_id", None) or room_id or topic_id or participant_identity or getattr(raw, "id", None) or "") or ""
            display_name = _safe_text(getattr(raw, "display_name", None) or getattr(raw, "alias", None) or getattr(raw, "room_name", None) or getattr(raw, "topic_title", None) or participant_identity or thread_id) or thread_id
            unread_count = _safe_int(getattr(raw, "unread_count", 0) or 0, minimum=0)
        if not thread_id:
            continue
        latest = _message_record(thread_id, raw)
        threads.append(
            MailThreadRecord(
                thread_id=thread_id,
                scope_kind=scope,
                display_name=display_name,
                participant_identity=_safe_text(participant_identity),
                unread_count=unread_count,
                latest_message=latest,
                transports=_transports(raw, latest),
                group=_group_meta(raw) if scope == ConversationScopeKind.GROUP else None,
                forum=_forum_meta(raw) if scope == ConversationScopeKind.FORUM else None,
            )
        )
    threads.sort(key=lambda record: record.latest_message.timestamp if record.latest_message and record.latest_message.timestamp is not None else 0.0, reverse=True)
    return MailIndexState(
        threads=tuple(threads),
        by_thread_id={thread.thread_id: thread for thread in threads},
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=now),
    )

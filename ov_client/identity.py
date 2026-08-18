"""Identity derivation: X-OpenViking-Agent and per-venue session ids.

The hosted OpenViking Context service scopes memory by the
``X-OpenViking-Agent`` header plus the authenticated API key. We give every
conversation scope (user or group) a stable agent id so memories never leak
across chats, and derive a deterministic, URL-safe session id per scope.
"""

from __future__ import annotations

import hashlib
import re

from .config import PluginConfig

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def _clean(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def derive_agent_id(
    cfg: PluginConfig,
    platform: str,
    group_id: str = "",
    sender_id: str = "",
) -> str:
    """Build the X-OpenViking-Agent value for one conversation scope.

    With scope_isolation on (default), group chats get
    ``<prefix>:<platform>:group:<group_id>`` and private chats get
    ``<prefix>:<platform>:user:<sender_id>``. With it off, all conversations
    share ``<prefix>`` (one global memory space).
    """
    prefix = _clean(cfg.agent_id_prefix, "astrbot")
    platform_clean = _clean(platform, "unknown").lower()
    if not cfg.scope_isolation:
        return prefix
    if str(group_id or "").strip():
        return f"{prefix}:{platform_clean}:group:{_clean(group_id, '0')}"
    return f"{prefix}:{platform_clean}:user:{_clean(sender_id, '0')}"


def derive_session_id(agent_id: str) -> str:
    """Deterministic session id for an agent scope (stable across restarts)."""
    digest = hashlib.md5(agent_id.encode("utf-8")).hexdigest()[:16]
    return f"astrbot-{digest}"


def safe_peer_id(sender_id: str) -> str:
    """A URL-safe peer label for a platform sender id."""
    cleaned = _UNSAFE.sub("_", str(sender_id or ""))[:64]
    return cleaned if cleaned else "anonymous"

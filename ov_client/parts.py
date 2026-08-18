"""Message part builders for OpenViking session payloads.

A message payload is: {"role": "user"|"assistant"|"system",
"parts": [{"type": "text", "text": "..."}], ...}.
"""

from __future__ import annotations

from typing import Any


def _text_part(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def user_text_part(
    text: str,
    sender_name: str = "",
    sender_id: str = "",
    is_group: bool = False,
    group_id: str = "",
) -> dict[str, str]:
    """Prefix origin info so extracted memories know who said what."""
    name = str(sender_name or sender_id or "用户").strip()
    if is_group:
        prefix = f"[group:{group_id} · {name}]"
    else:
        prefix = f"[{name}]"
    return _text_part(f"{prefix} {text}")


def assistant_text_part(text: str) -> dict[str, str]:
    return _text_part(str(text))


def tool_call_part(tool_name: str, tool_input: Any) -> dict[str, Any]:
    return {
        "type": "tool",
        "tool_name": str(tool_name or "unknown"),
        "tool_input": _jsonable(tool_input),
        "tool_status": "ok",
    }


def tool_result_part(tool_name: str, tool_result_text: str) -> dict[str, Any]:
    return {
        "type": "tool",
        "tool_name": str(tool_name or "unknown"),
        "tool_output": str(tool_result_text)[:2000],
        "tool_status": "done",
    }


def build_message(role: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"role": role, "parts": parts}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in list(value)[:50]]
    try:
        return str(value)
    except Exception:
        return None


def estimate_tokens(text: str) -> int:
    """Rough CJK-aware token estimate (same heuristic family as OV docs)."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u3000" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk * 1.5 + other / 4) + 1

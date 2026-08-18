"""Plugin configuration parsing and validation.

Reads the raw dict AstrBot passes into the plugin and exposes typed,
bounded attributes. Unknown keys are ignored so older configs keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RECALL_MODES = ("auto", "tool", "both", "off")
RECALL_APIS = ("find", "context")
ACCESS_MODES = ("free", "admin", "off")


def access_allowed(mode: str, is_admin: bool) -> bool:
    """Pure permission check for the three-value access switches.

    mode "free" -> everyone allowed; "admin" -> only admins; "off" -> nobody.
    """
    mode = str(mode or "free").strip().lower()
    if mode == "off":
        return False
    if mode == "admin":
        return bool(is_admin)
    return True


def _bounded(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    return int(_bounded(value, default, minimum, maximum))


def _enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


@dataclass
class PluginConfig:
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ov_base_url(self) -> str:
        return str(self.raw.get("ov_base_url") or "https://api.vikingdb.cn-beijing.volces.com/openviking").rstrip("/")

    @property
    def ov_api_key(self) -> str:
        return str(self.raw.get("ov_api_key") or "").strip()

    @property
    def agent_id_prefix(self) -> str:
        prefix = str(self.raw.get("agent_id_prefix") or "astrbot").strip()
        return prefix or "astrbot"

    @property
    def scope_isolation(self) -> bool:
        return bool(self.raw.get("scope_isolation", True))

    @property
    def capture_enabled(self) -> bool:
        return bool(self.raw.get("capture_enabled", True))

    @property
    def capture_bot_replies(self) -> bool:
        return bool(self.raw.get("capture_bot_replies", True))

    @property
    def recall_mode(self) -> str:
        return _enum(self.raw.get("recall_mode"), RECALL_MODES, "auto")

    @property
    def recall_api(self) -> str:
        return _enum(self.raw.get("recall_api"), RECALL_APIS, "find")

    @property
    def recall_limit(self) -> int:
        return _bounded_int(self.raw.get("recall_limit"), 8, 1, 30)

    @property
    def recall_min_score(self) -> float:
        return _bounded(self.raw.get("recall_min_score"), 0.35, 0.0, 1.0)

    @property
    def recall_token_budget(self) -> int:
        return _bounded_int(self.raw.get("recall_token_budget"), 2000, 200, 8000)

    @property
    def recall_target_uri(self) -> str:
        return str(self.raw.get("recall_target_uri") or "").strip()

    @property
    def commit_message_threshold(self) -> int:
        return _bounded_int(self.raw.get("commit_message_threshold"), 20, 2, 500)

    @property
    def commit_token_threshold(self) -> int:
        return _bounded_int(self.raw.get("commit_token_threshold"), 4096, 256, 100000)

    @property
    def commit_idle_seconds(self) -> int:
        return _bounded_int(self.raw.get("commit_idle_seconds"), 1800, 30, 86400)

    @property
    def capture_tool_io(self) -> bool:
        return bool(self.raw.get("capture_tool_io", False))

    # -- three-value access switches (free / admin / off) ----------------------

    @property
    def capture_access(self) -> str:
        """对话捕获权限：free=所有对话 / admin=仅管理员对话 / off=不捕获。"""
        return _enum(self.raw.get("capture_access"), ACCESS_MODES, "free")

    @property
    def recall_access(self) -> str:
        """自动召回注入权限。"""
        return _enum(self.raw.get("recall_access"), ACCESS_MODES, "free")

    @property
    def tool_access(self) -> str:
        """LLM 工具权限；off 时不注册工具（模型看不到）。"""
        return _enum(self.raw.get("tool_access"), ACCESS_MODES, "free")

    @property
    def command_access(self) -> str:
        """管理命令权限；off 时命令返回已禁用。"""
        return _enum(self.raw.get("command_access"), ACCESS_MODES, "free")

    @property
    def request_timeout_seconds(self) -> int:
        return _bounded_int(self.raw.get("request_timeout_seconds"), 60, 10, 300)

    @property
    def debug_log(self) -> bool:
        return bool(self.raw.get("debug_log", False))

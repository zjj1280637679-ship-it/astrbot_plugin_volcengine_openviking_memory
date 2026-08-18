"""Commit scheduler: when to trigger memory extraction.

Memory extraction on the hosted service happens when a session is committed.
Committing every message is wasteful, so we batch: commit when the pending
message count or estimated tokens cross thresholds, or after an idle period.
State lives in memory per agent scope; a background loop flushes idle venues.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .client import OVClient, OVError
from .config import PluginConfig

logger = logging.getLogger("astrbot_plugin_volcengine_openviking_memory")


class CommitScheduler:
    def __init__(self, client: OVClient, cfg: PluginConfig) -> None:
        self.client = client
        self.cfg = cfg
        # agent_id -> {pending_messages, pending_tokens, last_commit_ts}
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    # -- accounting -----------------------------------------------------------

    def _entry(self, agent_id: str) -> dict[str, Any]:
        if agent_id not in self._state:
            self._state[agent_id] = {
                "pending_messages": 0,
                "pending_tokens": 0,
                "last_commit_ts": 0,
                "session_id": "",
            }
        return self._state[agent_id]

    async def record_message(self, agent_id: str, session_id: str, tokens: int) -> None:
        async with self._lock:
            entry = self._entry(agent_id)
            entry["session_id"] = session_id
            entry["pending_messages"] += 1
            entry["pending_tokens"] += int(tokens)

    async def evaluate(self, agent_id: str, session_id: str) -> bool:
        """Commit when thresholds are crossed. Returns True if committed."""
        async with self._lock:
            entry = self._entry(agent_id)
            entry["session_id"] = session_id
            messages = entry["pending_messages"]
            tokens = entry["pending_tokens"]
        if messages >= self.cfg.commit_message_threshold or tokens >= self.cfg.commit_token_threshold:
            return await self.commit(agent_id, session_id)
        return False

    async def commit(self, agent_id: str, session_id: str) -> bool:
        async with self._lock:
            entry = self._entry(agent_id)
            messages = entry["pending_messages"]
            tokens = entry["pending_tokens"]
            entry["pending_messages"] = 0
            entry["pending_tokens"] = 0
            entry["last_commit_ts"] = int(time.time())
            entry["session_id"] = session_id
        if messages <= 0 and tokens <= 0:
            return False
        try:
            result = await self.client.commit_session(session_id, agent_id)
            if self.cfg.debug_log:
                logger.info(
                    "[OV] commit %s (msgs=%d tokens=%d) -> %s",
                    agent_id, messages, tokens, result,
                )
            return True
        except OVError as exc:
            # Restore pending so a later attempt retries the same content.
            entry = self._entry(agent_id)
            entry["pending_messages"] += messages
            entry["pending_tokens"] += tokens
            logger.warning("[OV] commit %s failed: %s", agent_id, exc)
            return False

    def status(self, agent_id: str) -> dict[str, Any]:
        entry = self._entry(agent_id)
        return {
            "pending_messages": entry["pending_messages"],
            "pending_tokens": entry["pending_tokens"],
            "last_commit_ts": entry["last_commit_ts"],
        }

    # -- background idle flush -------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._idle_loop(), name="ov-commit-idle")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _idle_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(min(self.cfg.commit_idle_seconds, 60))
                now = int(time.time())
                for agent_id in list(self._state.keys()):
                    entry = self._state[agent_id]
                    if entry["pending_messages"] <= 0:
                        continue
                    idle = now - max(entry["last_commit_ts"], 0)
                    if idle >= self.cfg.commit_idle_seconds:
                        await self.commit(agent_id, entry["session_id"])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[OV] idle commit loop error")

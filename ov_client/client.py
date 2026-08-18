"""Async HTTP client for the hosted Volcengine OpenViking Context service.

Targets the Agent-记忆 (OpenViking Context) hosted API:
    base:  https://api.vikingdb.cn-beijing.volces.com/openviking
    auth:  Authorization: Bearer <OpenViking API Key>
    scope: X-OpenViking-Agent: <agent_id>

Only lossless JSON crosses the wire; errors are caught and reported so a
failed write/recall never breaks the AstrBot chat pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger("astrbot_plugin_volcengine_openviking_memory")


class OVError(Exception):
    """Raised for unrecoverable service errors (non-HTTP-200)."""


class OVClient:
    """Thin async wrapper over the OpenViking REST endpoints the plugin needs."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
        debug: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.debug = debug
        self._http = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        try:
            await self._http.aclose()
        except Exception:
            pass

    # -- low level ------------------------------------------------------------

    def _headers(self, agent_id: str = "") -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if agent_id:
            headers["X-OpenViking-Agent"] = agent_id
        return headers

    def _log(self, method: str, url: str, status: int, body: str = "") -> None:
        if self.debug:
            logger.info("[OV] %s %s -> %s %s", method, url, status, body[:300])

    async def _post(self, path: str, payload: dict, agent_id: str = "") -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = await self._http.post(
                url, headers=self._headers(agent_id), json=payload
            )
        except httpx.HTTPError as exc:
            raise OVError(f"网络错误 {url}: {exc}") from exc
        self._log("POST", url, resp.status_code, resp.text[:300])
        if resp.status_code != 200:
            raise OVError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise OVError("响应不是 JSON") from exc

    async def _get(self, path: str, agent_id: str = "") -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = await self._http.get(url, headers=self._headers(agent_id))
        except httpx.HTTPError as exc:
            raise OVError(f"网络错误 {url}: {exc}") from exc
        self._log("GET", url, resp.status_code, resp.text[:300])
        if resp.status_code != 200:
            raise OVError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise OVError("响应不是 JSON") from exc

    @staticmethod
    def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
        result = body.get("result")
        return result if isinstance(result, dict) else {}

    # -- health ---------------------------------------------------------------

    async def health(self) -> bool:
        try:
            resp = await self._http.get(f"{self.base_url}/health", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    # -- sessions -------------------------------------------------------------

    async def create_session(
        self, session_id: str, agent_id: str = ""
    ) -> dict[str, Any]:
        body = await self._post(
            "/api/v1/sessions", {"session_id": session_id}, agent_id
        )
        return self._unwrap(body)

    async def get_session(
        self, session_id: str, agent_id: str = "", auto_create: bool = False
    ) -> dict[str, Any] | None:
        q = "?auto_create=true" if auto_create else ""
        try:
            body = await self._get(
                f"/api/v1/sessions/{quote(session_id)}{q}", agent_id
            )
        except OVError:
            return None
        return self._unwrap(body)

    async def ensure_session(
        self, session_id: str, agent_id: str = ""
    ) -> dict[str, Any]:
        """Get the session, creating it (with the deterministic id) if needed."""
        existing = await self.get_session(session_id, agent_id)
        if existing:
            return existing
        return await self.create_session(session_id, agent_id)

    async def add_message(
        self,
        session_id: str,
        payload: dict[str, Any],
        agent_id: str = "",
    ) -> bool:
        body = await self._post(
            f"/api/v1/sessions/{quote(session_id)}/messages", payload, agent_id
        )
        return bool(body.get("status") == "ok" or "result" in body)

    async def commit_session(
        self, session_id: str, agent_id: str = ""
    ) -> dict[str, Any]:
        body = await self._post(
            f"/api/v1/sessions/{quote(session_id)}/commit",
            {"telemetry": False},
            agent_id,
        )
        return self._unwrap(body)

    async def delete_uri(self, uri: str, agent_id: str = "", recursive: bool = True, retries: int = 3) -> dict[str, Any]:
        """Delete a viking:// file or directory (idempotent).

        The hosted service can transiently return 503 (lock lease errors) under
        concurrent ops; retry a few times before giving up.
        """
        import urllib.parse as _parse
        import asyncio as _aio

        path = f"/api/v1/fs?uri={_parse.quote(uri, safe='/:@')}&recursive={str(recursive).lower()}"
        url = f"{self.base_url}{path}"
        last_exc: OVError | None = None
        for attempt in range(max(1, retries)):
            try:
                resp = await self._http.request(
                    "DELETE", url, headers=self._headers(agent_id)
                )
                self._log("DELETE", url, resp.status_code, resp.text[:300])
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except json.JSONDecodeError as exc:
                        raise OVError("响应不是 JSON") from exc
                if resp.status_code != 503:
                    raise OVError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                # 503: transient lock/backend unavailability -> retry
                last_exc = OVError(f"HTTP 503: {resp.text[:200]}")
            except httpx.HTTPError as exc:
                raise OVError(f"网络错误 {url}: {exc}") from exc
            if attempt + 1 < max(1, retries):
                await _aio.sleep(2 + attempt * 2)
        raise OVError(str(last_exc or "删除失败（服务暂时不可用）"))

    # -- knowledge base (resources) -------------------------------------------

    async def write_content(
        self,
        uri: str,
        content: str,
        mode: str = "create",
        wait: bool = True,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """Write a text knowledge entry to a viking:// resources URI."""
        body = await self._post(
            "/api/v1/content/write",
            {"uri": uri, "content": content, "mode": mode, "wait": wait},
            agent_id,
        )
        return self._unwrap(body)

    async def read_content(self, uri: str, agent_id: str = "") -> str:
        """Read raw text content of a viking:// file (result is a plain string)."""
        import urllib.parse as _parse

        body = await self._get(
            f"/api/v1/content/read?uri={_parse.quote(uri, safe='/:@')}", agent_id
        )
        result = body.get("result")
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return str(result.get("content") or result.get("text") or "")
        return ""

    async def list_dir(self, uri: str, agent_id: str = "", recursive: bool = False) -> list[dict[str, Any]]:
        """List entries under a viking:// directory."""
        import urllib.parse as _parse

        q = f"uri={_parse.quote(uri, safe='/:@')}"
        if recursive:
            q += "&recursive=true"
        body = await self._get(f"/api/v1/fs/ls?{q}", agent_id)
        result = body.get("result")
        if isinstance(result, list):
            return result
        return []

    # -- search ---------------------------------------------------------------

    async def find(
        self,
        query: str,
        agent_id: str = "",
        limit: int = 8,
        score_threshold: float = 0.0,
        target_uri: str = "",
    ) -> list[dict[str, Any]]:
        """List-mode semantic recall. Returns flattened MatchedContext items."""
        payload: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "score_threshold": score_threshold,
        }
        if target_uri:
            payload["target_uri"] = target_uri
        body = await self._post("/api/v1/search/find", payload, agent_id)
        result = body.get("result")
        if not isinstance(result, dict):
            return []
        items: list[dict[str, Any]] = []
        for key in ("memories", "resources", "skills"):
            group = result.get(key)
            if isinstance(group, list):
                items.extend(group)
        return items

    async def search_context(
        self,
        query: str,
        agent_id: str = "",
        max_tokens: int = 2000,
        purpose: str = "chat",
    ) -> str | None:
        """Server-assembled recall via /search mode=context.

        Returns the ``rendered`` injection block, or None when the hosted
        service rejects context mode (caller falls back to find()).
        """
        payload: dict[str, Any] = {
            "query": query,
            "mode": "context",
            "max_tokens": max_tokens,
            "purpose": purpose,
        }
        try:
            body = await self._post("/api/v1/search/search", payload, agent_id)
        except OVError as exc:
            logger.warning("[OV] search context unsupported, fallback to find: %s", exc)
            return None
        result = body.get("result")
        if not isinstance(result, dict):
            return None
        rendered = result.get("rendered") or ""
        if not rendered:
            entries = result.get("entries")
            if isinstance(entries, list):
                rendered = "\n".join(
                    f"- [{e.get('category', 'memory')} {int((e.get('score') or 0) * 100)}%] "
                    f"{e.get('text', '')}"[:500]
                    for e in entries
                )
        return rendered or None

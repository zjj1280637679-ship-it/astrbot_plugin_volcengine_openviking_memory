"""Semantic recall from OpenViking and injection-block formatting.

find() mode returns ranked hits that we filter, re-rank with light boosts
(preference / leaf / lexical overlap) and dedup before formatting. context
mode delegates assembly to the server and returns its rendered block.
"""

from __future__ import annotations

import re
from typing import Any

from .client import OVClient
from .config import PluginConfig

_PREFERENCE_RE = re.compile(
    r"prefer|preference|favorite|favourite|like|偏好|喜欢|爱好|更倾向|讨厌|不喜欢", re.I
)
_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]{2,}", re.I)
_STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "did", "does", "is", "are", "was", "were", "the", "and", "for", "with",
    "from", "that", "this", "your", "you", "请", "一下",
}


def _query_profile(query: str) -> dict:
    tokens = [t for t in _TOKEN_RE.findall(query.lower()) if t not in _STOPWORDS]
    return {
        "tokens": tokens,
        "wants_preference": bool(_PREFERENCE_RE.search(query)),
    }


def _lexical_overlap(tokens: list[str], text: str) -> float:
    if not tokens or not text:
        return 0.0
    haystack = f" {text.lower()} "
    matched = sum(1 for t in tokens[:8] if t in haystack)
    return min(0.2, (matched / min(len(tokens), 4)) * 0.2)


def _rank(item: dict, profile: dict) -> float:
    base = max(0.0, min(1.0, item.get("score", 0)))
    abstract = (item.get("abstract") or item.get("overview") or "").strip()
    uri = str(item.get("uri") or "").lower()
    leaf_boost = 0.12 if item.get("level") == 2 or uri.endswith(".md") else 0.0
    pref_boost = 0.08 if profile["wants_preference"] and "/preferences/" in uri else 0.0
    return base + leaf_boost + pref_boost + _lexical_overlap(profile["tokens"], f"{uri} {abstract}")


def _dedup(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = str(it.get("uri") or "")
        if not key:
            key = (it.get("abstract") or "").strip().lower()[:120]
        if not key:
            key = f"score:{it.get('score')}"
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def _format_find_block(items: list[dict], cfg: PluginConfig) -> str:
    lines = [
        "<openviking-context>",
        "这是来自长期记忆的相关上下文，仅作参考，不要编造其中没有的信息：",
    ]
    for item in items:
        score_pct = max(0, min(100, int((item.get("score") or 0) * 100)))
        uri = str(item.get("uri") or "")
        body = (item.get("abstract") or item.get("overview") or "").strip()
        if not body:
            continue
        line = f"[记忆 {score_pct}% · {uri}]\n{body[: cfg.recall_token_budget // max(len(items), 1) * 2]}"
        lines.append(line)
    lines.append("</openviking-context>")
    return "\n\n".join(lines)


async def recall_and_format(
    client: OVClient,
    cfg: PluginConfig,
    query: str,
    agent_id: str,
) -> str | None:
    """Recall relevant memory for ``query`` and return an injectable block."""
    if not query.strip():
        return None

    if cfg.recall_api == "context":
        block = await client.search_context(
            query,
            agent_id=agent_id,
            max_tokens=cfg.recall_token_budget,
            purpose="chat",
        )
        if block:
            return f"<openviking-context>\n{block}\n</openviking-context>"
        # Fall through to find() when the hosted service rejects context mode.

    items = await client.find(
        query,
        agent_id=agent_id,
        limit=max(cfg.recall_limit * 2, 8),
        score_threshold=cfg.recall_min_score,
        target_uri=cfg.recall_target_uri,
    )
    if not items:
        return None

    profile = _query_profile(query)
    filtered = [it for it in items if it.get("score", 0) >= cfg.recall_min_score]
    filtered.sort(key=lambda it: _rank(it, profile), reverse=True)
    picked = _dedup(filtered)[: cfg.recall_limit]
    if not picked:
        return None
    return _format_find_block(picked, cfg)


async def recall_for_tool(
    client: OVClient,
    cfg: PluginConfig,
    query: str,
    agent_id: str,
    limit: int = 0,
) -> dict:
    """Recall for the model-callable tool; returns a JSON-safe result dict."""
    effective_limit = max(1, min(limit or cfg.recall_limit, 30))
    items = await client.find(
        query,
        agent_id=agent_id,
        limit=max(effective_limit * 2, 8),
        score_threshold=cfg.recall_min_score,
        target_uri=cfg.recall_target_uri,
    )
    profile = _query_profile(query)
    filtered = [it for it in items if it.get("score", 0) >= cfg.recall_min_score]
    filtered.sort(key=lambda it: _rank(it, profile), reverse=True)
    picked = _dedup(filtered)[:effective_limit]
    return {
        "query": query,
        "count": len(picked),
        "results": [
            {
                "uri": str(it.get("uri") or ""),
                "type": str(it.get("context_type") or it.get("category") or "memory"),
                "score": round(float(it.get("score") or 0.0), 3),
                "text": (it.get("abstract") or it.get("overview") or "").strip()[:800],
            }
            for it in picked
        ],
    }

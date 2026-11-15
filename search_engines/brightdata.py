"""Bright Data SERP 引擎（新 API 模式）：POST api.brightdata.com/request 取百度 SERP JSON。

免费层 5000 credits/月、官方支持百度、无需绑卡。配置两个环境变量：
- BRIGHTDATA_API_TOKEN：控制台 Settings → API token（账户级）
- BRIGHTDATA_ZONE：（可选）Zone 名，默认 "serp"——由 SERP API 产品页激活时自动创建
旧的代理凭据模式（BRIGHTDATA_PROXY_USER/PASSWORD）已废弃。
"""
from __future__ import annotations

import os
import time
from urllib.parse import quote

from .http import http_post_json
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_ENDPOINT = "https://api.brightdata.com/request"
_TOKEN_ENV = "BRIGHTDATA_API_TOKEN"
_ZONE_ENV = "BRIGHTDATA_ZONE"
_MAX_RESULTS = 10


def has_key() -> bool:
    return bool(os.environ.get(_TOKEN_ENV, "").strip())


_zone_cache: str | None = None


def get_zone() -> str:
    """Zone 解析顺序：环境变量 → API 自动发现（get_active_zones，优先含 serp 的）→ 默认 serp。"""
    global _zone_cache
    env = os.environ.get(_ZONE_ENV, "").strip()
    if env:
        return env
    if _zone_cache:
        return _zone_cache
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        return "serp"
    try:
        from .http import http_get

        r = http_get(
            "https://api.brightdata.com/zone/get_active_zones",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8.0,
        )
        if r.status_code == 200:
            zones = r.json()
            if isinstance(zones, list) and zones:
                names = [z if isinstance(z, str) else str(z.get("name") or z.get("zone") or "") for z in zones]
                names = [n for n in names if n]
                preferred = [n for n in names if "serp" in n.lower()]
                _zone_cache = (preferred or names)[0]
    except Exception:
        pass
    return _zone_cache or "serp"


def fetch_raw(
    query: str,
    *,
    lang: str = "zh",
    page: int = 1,
    timeout: float = 15.0,
    target: str = "baidu",
    data_format: str | None = None,
    fmt: str = "json",
    country: str | None = None,
) -> dict:
    """诊断转储：/api/debug/raw?engine=brightdata&target=google|baidu&df=none&fmt=raw&country=cn。"""
    token = os.environ.get(_TOKEN_ENV, "").strip()
    zone = get_zone()
    if target == "google":
        target_url = f"https://www.google.com/search?q={quote(query)}"
    else:
        target_url = f"https://www.baidu.com/s?wd={quote(query)}&rn=10&pn={(page - 1) * 10}"
    payload: dict = {"zone": zone, "url": target_url, "format": fmt}
    if data_format:
        payload["data_format"] = data_format
    if country:
        payload["country"] = country
    resp = http_post_json(
        _ENDPOINT,
        payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    return {"http_status": resp.status_code, "url": target_url, "body_head": resp.text[:3000], "body_full": resp.text}


def _extract_list(data: dict) -> list[dict]:
    for key in ("organic", "results", "organic_results", "items", "result"):
        v = data.get(key)
        if isinstance(v, list) and v:
            return [r for r in v if isinstance(r, dict)]
    return []


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 15.0,
    deadline: float | None = None,  # 契约统一；单请求引擎不使用
) -> dict:
    started = time.perf_counter()
    if lang != "zh":
        return {"name": "brightdata", "status": "skipped", "latency_ms": 0, "results": [], "note": "百度源，英文查询自动跳过"}
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        return {
            "name": "brightdata",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 BRIGHTDATA_API_TOKEN（控制台 Settings 生成；SERP API 免费层 5000/月）",
        }
    zone = get_zone()

    blocked = baseline_block or []
    target = f"https://www.baidu.com/s?wd={quote(query)}&rn=10&pn={(page - 1) * 10}"
    resp = http_post_json(
        _ENDPOINT,
        {"zone": zone, "url": target, "format": "json"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if resp.status_code == 401 or resp.status_code == 403:
        raise EngineError(f"HTTP {resp.status_code}（API token 无效）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    text = resp.text.strip()
    data = None
    if text.startswith("{") or text.startswith("["):
        import json

        try:
            data = json.loads(text)
        except Exception:
            data = None
    if not isinstance(data, dict):
        return {
            "name": "brightdata",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "响应非 SERP JSON（zone 配置或格式参数问题）",
            "discarded_sample": [text[:120]],
        }

    rows = _extract_list(data)
    tokens = relevance_tokens(query)
    items: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        url = r.get("url") or r.get("link") or ""  # parsed_light 形态用 link 字段
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        title = str(r.get("title") or url).strip()
        snippet = str(r.get("description") or r.get("snippet") or r.get("abstract") or "").strip()
        items.append({"title": title, "url": url, "domain": domain, "snippet": snippet})
        if len(items) >= _MAX_RESULTS:
            break

    if items and tokens and not any(overlap_any(tokens, r["title"], r["snippet"]) for r in items):
        return {
            "name": "brightdata",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "相关性校验未通过，已丢弃",
            "discarded_sample": [i["title"][:80] for i in items[:3]],
        }

    return {
        "name": "brightdata",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

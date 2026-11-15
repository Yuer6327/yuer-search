"""Bright Data 引擎（Google 结果源）：POST api.brightdata.com/request，目标 URL 拼 brd_json=1
触发解析输出（organic[].link/title/description）。免费层 5000 credits/月循环、无需绑卡。

曾尝试百度目标（官方产品页宣称支持百度）——实测所有参数组合均 >25s 挂起，遂转为 Google 源；
百度中文由 Bing 主力覆盖。zone 经 get_active_zones 自动发现。
"""
from __future__ import annotations

import os
import time
from urllib.parse import quote

from .http import http_post_json
from .util import EngineError, domain_of, host_matches

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
    brd_json: bool = False,
) -> dict:
    """诊断转储：/api/debug/raw?engine=brightdata&target=google|baidu&df=none&fmt=raw&country=cn。"""
    token = os.environ.get(_TOKEN_ENV, "").strip()
    zone = get_zone()
    if target == "google":
        target_url = f"https://www.google.com/search?q={quote(query)}"
        if brd_json:
            target_url += "&brd_json=1"
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
    timeout: float = 8.0,
    deadline: float | None = None,  # 契约统一；单请求引擎不使用
) -> dict:
    """Google 结果源（5000/月循环额度）。目标 URL 拼 brd_json=1 触发解析输出，
    响应为 {status_code, headers, body} 包装，body 是解析后的 SERP JSON（organic[].link）。"""
    started = time.perf_counter()
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
    target_url = f"https://www.google.com/search?q={quote(query)}&brd_json=1"
    if page > 1:
        target_url += f"&start={(page - 1) * 10}"
    resp = http_post_json(
        _ENDPOINT,
        {"zone": zone, "url": target_url, "format": "json"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if resp.status_code == 401 or resp.status_code == 403:
        raise EngineError(f"HTTP {resp.status_code}（API token 无效）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    import json as _json

    wrapper = resp.json()
    body = wrapper.get("body", "") if isinstance(wrapper, dict) else ""
    if not body.strip().startswith("{"):
        # 非 parsed 输出（zone 配置漂移）——降级并留样本
        return {
            "name": "brightdata",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "响应体不是解析后的 SERP JSON",
            "discarded_sample": [body[:120]],
        }
    inner = _json.loads(body)

    items: list[dict] = []
    seen: set[str] = set()
    for r in inner.get("organic") or []:
        url = r.get("link") or r.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append(
            {
                "title": str(r.get("title") or url).strip(),
                "url": url,
                "domain": domain,
                "snippet": str(r.get("description") or "").strip(),
            }
        )
        if len(items) >= _MAX_RESULTS:
            break

    return {
        "name": "brightdata",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

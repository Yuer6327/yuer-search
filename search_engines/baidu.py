"""百度搜索引擎：tn=json JSON 接口（searxng 官方同款路线，放弃 HTML 抓取）。

数据中心 IP 的验证码（wappass 302 / "百度安全验证"）触发率高——护栏：
- 检测到验证码 → 模块级冷却 10 分钟（冷却期内直接跳过，不白耗上游请求）；
- 结果侧相关性护栏 + 基线域名过滤；
- 验证码/异常一律静默降级，绝不承担主力职责（主力是已验证可用的 Bing 中文）。
百度 -site: 支持不明，不做服务端下推。
"""
from __future__ import annotations

import re
import time

from .http import http_get
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_API = "https://www.baidu.com/s"
_MAX_RESULTS = 10
_COOLDOWN_SECONDS = 600

_cooldown_until = 0.0  # 模块级：验证码触发后冷却（随函数实例生命周期，够用）


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse(data: dict, blocked: list[str]) -> list[dict]:
    feed = data.get("feed") or {}
    entries = feed.get("entry") or []
    items: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        url = e.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        if "baidu.com/link" in url:  # 重定向包装链接，域展示错误，跳过
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append(
            {"title": _clean(e.get("title")) or url, "url": url, "domain": domain, "snippet": _clean(e.get("abs"))}
        )
        if len(items) >= _MAX_RESULTS:
            break
    return items


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 6.0,
    deadline: float | None = None,  # 契约统一；单请求引擎不使用
) -> dict:
    global _cooldown_until
    started = time.perf_counter()
    if lang != "zh":
        return {
            "name": "baidu",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "中文引擎，英文查询自动跳过",
        }
    if time.time() < _cooldown_until:
        return {
            "name": "baidu",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": f"验证码冷却中（剩 {int(_cooldown_until - time.time())}s）",
        }

    blocked = baseline_block or []
    params = {"wd": query, "rn": "10", "pn": str((page - 1) * 10), "tn": "json"}
    resp = http_get(_API, params=params, timeout=timeout)
    final_url = str(getattr(resp, "url", ""))
    if resp.status_code != 200 or "wappass" in final_url or "验证" in resp.text[:2000]:
        _cooldown_until = time.time() + _COOLDOWN_SECONDS
        raise EngineError("触发百度验证码（wappass），冷却 10 分钟")

    try:
        data = resp.json()
    except Exception:
        _cooldown_until = time.time() + _COOLDOWN_SECONDS
        raise EngineError("响应非 JSON（疑似验证码页），冷却 10 分钟") from None
    if data.get("antiFlag") == 1:
        _cooldown_until = time.time() + _COOLDOWN_SECONDS
        raise EngineError("百度返回 antiFlag=1（风控拒绝），冷却 10 分钟")

    items = _parse(data, blocked)
    tokens = relevance_tokens(query)
    if items and tokens and not any(overlap_any(tokens, r["title"], r["snippet"]) for r in items):
        return {
            "name": "baidu",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "相关性校验未通过，已丢弃",
            "discarded_sample": [i["title"][:80] for i in items[:3]],
        }

    return {
        "name": "baidu",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

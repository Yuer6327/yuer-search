"""Bing 引擎：www.bing.com/search 抓取，中文结果主力源。

searxng 社区 2026 年实测：Bing 反爬烈度最低、无 TLS 指纹也可抓；
但它的坑在"静默垃圾"而非封锁。护栏（必须）：
1. 必带 mkt 参数（zh-CN / en-US）——缺参数时 Bing 会返回与查询无关的随机结果；
2. 相关性校验：结果与查询零词元重叠 → 标记 degraded 并丢弃全部结果，
   交给其他引擎兜底，防止垃圾静默污染聚合；
3. 解析器多选择器兜底，防 HTML class 混淆变更；广告位（b_ad）一律剔除。
"""
from __future__ import annotations

import base64
import re
import time
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .http import http_get
from .util import EngineError, apply_pushdown, domain_of, host_matches

_MAX_RESULTS = 15


def _unwrap_bing(href: str | None) -> str | None:
    """新版权威链接包在 bing.com/ck/a?...&u=a1<base64url> 重定向里，解出真实地址。"""
    if not href:
        return None
    if "bing.com/ck/a" in href:
        raw = parse_qs(urlparse(href).query).get("u", [""])[0]
        if raw.startswith("a1"):
            b64 = raw[2:]
            try:
                decoded = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
                target = decoded.decode("utf-8", "replace")
                return target if target.startswith("http") else None
            except Exception:
                return None
    return href if href.startswith("http") else None


def _tokenize(query: str) -> set[str]:
    q = query.lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", q))
    cjk = re.findall(r"[\u4e00-\u9fff]", q)
    if len(cjk) == 1:
        tokens.add(cjk[0])
    tokens |= {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    return tokens


def _parse(html: str, blocked: list[str]) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    for li in soup.select("#b_results li.b_algo"):
        classes = li.get("class") or []
        if any("b_ad" in c for c in classes):  # 广告剔除——0 广告承诺
            continue
        a = li.select_one("h2 a") or li.select_one("a.tilk") or li.select_one("h2")
        if not a:
            continue
        url = _unwrap_bing(a.get("href"))
        if not url or url in seen:
            continue
        snip_el = li.select_one(".b_caption p") or li.select_one(".b_caption") or li.select_one("p")
        snippet = snip_el.get_text(" ", strip=True) if snip_el else ""
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append(
            {
                "title": a.get_text(" ", strip=True),
                "url": url,
                "domain": domain,
                "snippet": snippet,
            }
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
    started = time.perf_counter()
    blocked = baseline_block or []
    q = apply_pushdown(query, blocked)
    params: dict = {"q": q, "mkt": "zh-CN", "setlang": "zh-Hans"} if lang == "zh" else {
        "q": q,
        "mkt": "en-US",
        "setlang": "en",
    }
    if page > 1:
        params["first"] = str((page - 1) * 15 + 1)

    resp = http_get("https://www.bing.com/search", params=params, timeout=timeout)
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")
    lower_head = resp.text[:4000].lower()
    if "captcha" in lower_head or "verify" in lower_head:
        raise EngineError("触发验证码/风控页")

    items = _parse(resp.text, blocked)

    # 相关性护栏：全部结果与查询零词元重叠 → 丢弃（Bing 静默垃圾响应特征）
    tokens = _tokenize(query)
    if items and tokens:
        has_overlap = any(
            any(t in (r["title"] + " " + r["snippet"]).lower() for t in tokens) for r in items
        )
        if not has_overlap:
            return {
                "name": "bing",
                "status": "degraded",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "results": [],
                "note": "相关性校验未通过：疑似 Bing 返回无关结果，已丢弃",
            }

    return {
        "name": "bing",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

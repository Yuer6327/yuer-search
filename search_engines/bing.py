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

from .http import http_session
from .util import EngineError, apply_pushdown, domain_of, host_matches
from .util import relevance_tokens as _tokenize  # noqa: F401  兼容测试引用

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


def _parse(html: str, blocked: list[str]) -> list[dict]:
    return _parse_soup(BeautifulSoup(html, "lxml"), blocked)


def _no_results_banner(soup: BeautifulSoup) -> bool:
    """识别 Bing 的显式"无结果"横幅——这是诚实的空结果，不是静默垃圾。"""
    if soup.select_one("#b_noResults"):
        return True
    head = soup.get_text(" ", strip=True)[:4000].lower()
    return any(m in head for m in ("there are no results for", "没有找到", "未找到"))


def _parse_soup(soup: BeautifulSoup, blocked: list[str]) -> list[dict]:
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
    params["form"] = "QBLH"  # 模拟真实浏览器从搜索框提交

    # 预热会话拿 Cookie（MUID 等）：数据中心 IP 缺 Cookie 时 Bing 会投毒返回随机无关结果
    search_headers = {"Referer": "https://www.bing.com/"}
    session = http_session()
    try:
        session.get("https://www.bing.com/", timeout=4.0)
    except Exception:
        pass  # 预热失败不阻塞主流程

    tokens = _tokenize(query)
    junk_sample: list[str] = []

    # 双入口尝试：www.bing.com 被投毒时换 cn.bing.com 重试一次（护栏二次校验）
    for host in ("https://www.bing.com", "https://cn.bing.com"):
        try:
            resp = session.get(
                f"{host}/search",
                params=params,
                headers=search_headers,
                timeout=timeout,
            )
        except Exception as exc:
            raise EngineError(f"{type(exc).__name__}") from exc
        if resp.status_code != 200:
            junk_sample = []
            continue
        lower_head = resp.text[:4000].lower()
        if "captcha" in lower_head or "verify" in lower_head:
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        if _no_results_banner(soup):
            return {
                "name": "bing",
                "status": "ok",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "results": [],
                "note": "无结果（Bing 显式空结果页）",
            }

        items = _parse_soup(soup, blocked)

        # 相关性护栏：全部结果与查询零词元重叠 → 判定为投毒垃圾，换入口重试
        if items and tokens:
            has_overlap = any(
                any(t in (r["title"] + " " + r["snippet"]).lower() for t in tokens) for r in items
            )
            if not has_overlap:
                junk_sample = [i["title"][:80] for i in items[:3]]
                continue  # 换下一个入口

        if items:
            return {
                "name": "bing",
                "status": "ok",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "results": items,
            }

    return {
        "name": "bing",
        "status": "degraded",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": [],
        "note": "相关性校验未通过：Bing 对云 IP 投毒返回无关结果（已尝试 www 与 cn 双入口）",
        "discarded_sample": junk_sample,
    }

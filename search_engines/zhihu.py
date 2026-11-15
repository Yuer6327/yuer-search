"""知乎开放平台引擎：global_search 全网搜索官方 API（Bearer Access Secret 鉴权）。

返回知乎站内问答/文章 + 全网结果，中文内容增量。官方文档：
https://developer.zhihu.com/docs?key=global_search
- 鉴权：Authorization: Bearer <Access Secret> + X-Request-Timestamp（秒级时间戳）；
- 业务错误以 HTTP 200 + JSON Code 表达（20001 鉴权失败 / 90001 请求失败）；
- 无翻页参数（响应有 HasMore 但无游标），仅做第一页；
- 结果链接带 utm_* 溯源参数，回链前剥离。
环境变量 ZHIHU_API_KEY 未配置时跳过。
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlparse

from .http import http_get
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_API = "https://developer.zhihu.com/api/v1/content/global_search"
_MAX_RESULTS = 12
_SNIPPET_MAX = 200
_UTM_RE = re.compile(r"^utm_", re.IGNORECASE)


def has_key() -> bool:
    return bool(os.environ.get("ZHIHU_API_KEY", "").strip())


def _strip_utm(url: str) -> str:
    """去掉 utm_* 溯源参数，其余 query 原样保留。"""
    try:
        parts = urlparse(url)
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _UTM_RE.match(k)])
        return parts._replace(query=query).geturl()
    except Exception:
        return url


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse(data: dict, blocked: list[str]) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for r in (data.get("Data") or {}).get("Items") or []:
        url = _strip_utm(r.get("Url") or "")
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        snippet = _clean(r.get("ContentText"))[:_SNIPPET_MAX]
        # 元信息后置：作者（匿名为「知乎用户」不打）、赞同/评论数仅非零时展示
        meta: list[str] = []
        author = _clean(r.get("AuthorName"))
        if author and author != "知乎用户":
            meta.append(author)
        if r.get("VoteUpCount"):
            meta.append(f"赞同 {r['VoteUpCount']}")
        if r.get("CommentCount"):
            meta.append(f"评论 {r['CommentCount']}")
        if meta:
            snippet = f"{snippet}｜{' · '.join(meta)}"
        items.append({"title": _clean(r.get("Title")) or url, "url": url, "domain": domain, "snippet": snippet})
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
    key = os.environ.get("ZHIHU_API_KEY", "").strip()
    if not key:
        return {
            "name": "zhihu",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 ZHIHU_API_KEY（developer.zhihu.com 开放平台获取 Access Secret）",
        }
    if page > 1:
        return {
            "name": "zhihu",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "接口无翻页参数，仅第一页",
        }

    resp = http_get(
        _API,
        params={"Query": query, "Count": str(_MAX_RESULTS)},
        headers={
            "Authorization": f"Bearer {key}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    code = data.get("Code")
    if code != 0:
        # 20001 鉴权失败 / 90001 请求失败等；Message 为官方受控文案，不含查询词
        raise EngineError(f"API code {code}: {data.get('Message')}")

    items = _parse(data, baseline_block or [])
    tokens = relevance_tokens(query)
    if items and tokens and not any(overlap_any(tokens, r["title"], r["snippet"]) for r in items):
        return {
            "name": "zhihu",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "相关性校验未通过，已丢弃",
            "discarded_sample": [i["title"][:80] for i in items[:3]],
        }

    return {
        "name": "zhihu",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

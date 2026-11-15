"""引擎共享工具：错误类型、-site: 下推、域名匹配、语言检测、相关性词元。"""
from __future__ import annotations

import re


class EngineError(Exception):
    """引擎硬失败（HTTP 错误/风控页/解析彻底失败）。消息不得包含查询词。"""


def apply_pushdown(query: str, blocked: list[str], max_sites: int = 12) -> str:
    """把基线屏蔽域名以 -site: 形式拼进查询，让屏蔽在上游就生效（不局限于第一页）。"""
    if not blocked:
        return query
    sites = " ".join(f"-site:{d}" for d in blocked[:max_sites])
    return f"{query} {sites}"


def relevance_tokens(query: str) -> set[str]:
    """相关性护栏词元：字母数字混合词（vue3/html5）额外拆出字母部分，
    避免 Bing 把 "vue3" 归一化成 "Vue.js 3" 时字面子串匹配不上而误杀；CJK 取相邻二元组。"""
    q = query.lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", q))
    for word in list(tokens):
        letters = re.findall(r"[a-z]{2,}", word)
        tokens.update(letters)
    cjk = re.findall(r"[\u4e00-\u9fff]", q)
    if len(cjk) == 1:
        tokens.add(cjk[0])
    tokens |= {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    return tokens


def overlap_any(tokens: set[str], *texts: str) -> bool:
    """任一词元出现在任一文本中（不区分大小写）。"""
    hay = " ".join(texts).lower()
    return any(t in hay for t in tokens)


def normalize_domain(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip(".")


def host_matches(host: str, domain: str) -> bool:
    """host 等于 domain，或是 domain 的子域名（example.com 覆盖 www./a.b.example.com）。"""
    return normalize_domain(host).endswith(normalize_domain(domain)) and (
        normalize_domain(host) == normalize_domain(domain)
        or normalize_domain(host).endswith("." + normalize_domain(domain))
    )


def detect_lang(query: str) -> str:
    """粗粒度语言检测：含 CJK 字符视为中文查询。"""
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in query) else "en"


def domain_of(url: str) -> str:
    from urllib.parse import urlparse

    return normalize_domain(urlparse(url).netloc)

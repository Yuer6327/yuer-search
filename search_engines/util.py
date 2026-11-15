"""引擎共享工具：错误类型、-site: 下推、域名匹配、语言检测。"""
from __future__ import annotations


class EngineError(Exception):
    """引擎硬失败（HTTP 错误/风控页/解析彻底失败）。消息不得包含查询词。"""


def apply_pushdown(query: str, blocked: list[str], max_sites: int = 12) -> str:
    """把基线屏蔽域名以 -site: 形式拼进查询，让屏蔽在上游就生效（不局限于第一页）。"""
    if not blocked:
        return query
    sites = " ".join(f"-site:{d}" for d in blocked[:max_sites])
    return f"{query} {sites}"


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

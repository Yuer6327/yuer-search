"""Yuer Search 引擎层：每个引擎实现 search(query, lang, page, baseline_block, timeout) -> dict。

返回 dict 统一形态：
    {"name", "status": ok|degraded|skipped, "latency_ms", "results": [{title,url,domain,snippet}], "note"?}
硬失败抛 EngineError（消息不得含查询词），由编排层转成 status=error。
"""
from .bing import search as bing_search
from .brave import search as brave_search, is_enabled as brave_enabled
from .ddg import search as ddg_search
from .marginalia import search as marginalia_search
from .util import EngineError, detect_lang, host_matches, normalize_domain

REGISTRY = {
    "ddg": ddg_search,
    "bing": bing_search,
    "marginalia": marginalia_search,
    "brave": brave_search,
}

__all__ = [
    "REGISTRY",
    "EngineError",
    "detect_lang",
    "host_matches",
    "normalize_domain",
    "brave_enabled",
    "bing_search",
    "brave_search",
    "ddg_search",
    "marginalia_search",
]

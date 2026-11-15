"""Yuer Search 引擎层：每个引擎实现 search(query, lang, page, baseline_block, timeout, deadline) -> dict。

返回 dict 统一形态：
    {"name", "status": ok|degraded|skipped, "latency_ms", "results": [{title,url,domain,snippet}], "note"?}
硬失败抛 EngineError（消息不得含查询词），由编排层转成 status=error。
"""
from .baidu import search as baidu_search
from .bilibili import search as bilibili_search
from .bing import search as bing_search
from .brave import search as brave_search, is_enabled as brave_enabled
from .cse import search as cse_search
from .ddg import search as ddg_search
from .marginalia import search as marginalia_search
from .mojeek import search as mojeek_search
from .serper import search as serper_search, has_key as serper_has_key
from .tavily import search as tavily_search, has_key as tavily_has_key
from .util import EngineError, detect_lang, host_matches, normalize_domain

REGISTRY = {
    "bing": bing_search,
    "google": cse_search,
    "ddg": ddg_search,
    "mojeek": mojeek_search,
    "bilibili": bilibili_search,
    "baidu": baidu_search,
    "marginalia": marginalia_search,
    "brave": brave_search,
    "tavily": tavily_search,
    "serper": serper_search,
}

__all__ = [
    "REGISTRY",
    "EngineError",
    "detect_lang",
    "host_matches",
    "normalize_domain",
    "brave_enabled",
    "tavily_has_key",
    "serper_has_key",
    "baidu_search",
    "bilibili_search",
    "bing_search",
    "brave_search",
    "cse_search",
    "ddg_search",
    "marginalia_search",
    "mojeek_search",
    "serper_search",
    "tavily_search",
]

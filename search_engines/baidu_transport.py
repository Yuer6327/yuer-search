"""百度"解锁代理"传输引擎：ScraperAPI / HasData（各 1000 credits/月免费、不绑卡）。

两个服务的免费层都是通用抓取代理——把它们当作百度 tn=json 接口的**传输通道**：
百度直抓触发 wappass 验证码时，由这些服务的代理网络代取（他们负责过验证码），
解析复用 baidu._parse。仅中文查询启用。
"""
from __future__ import annotations

import os
import time
from urllib.parse import quote

from .baidu import _parse as _baidu_parse
from .http import http_get
from .util import EngineError

_SCRAPERAPI_KEY_ENV = "SCRAPERAPI_KEY"
_HASDATA_KEY_ENV = "HASDATA_KEY"


def scraperapi_has_key() -> bool:
    return bool(os.environ.get(_SCRAPERAPI_KEY_ENV, "").strip())


def hasdata_has_key() -> bool:
    return bool(os.environ.get(_HASDATA_KEY_ENV, "").strip())


def _make_search(name: str, host: str, key_env: str, extra_params: dict | None = None):
    def search(
        query: str,
        *,
        lang: str = "en",
        page: int = 1,
        baseline_block: list[str] | None = None,
        timeout: float = 10.0,
        deadline: float | None = None,  # 契约统一；单请求引擎不使用
    ) -> dict:
        started = time.perf_counter()
        if lang != "zh":
            return {"name": name, "status": "skipped", "latency_ms": 0, "results": [], "note": "百度源，英文查询自动跳过"}
        key = os.environ.get(key_env, "").strip()
        if not key:
            return {
                "name": name,
                "status": "skipped",
                "latency_ms": 0,
                "results": [],
                "note": f"未配置 {key_env}",
            }

        target = f"https://www.baidu.com/s?wd={quote(query)}&rn=10&pn={(page - 1) * 10}&tn=json"
        params = {"api_key": key, "url": target, **(extra_params or {})}
        resp = http_get(host, params=params, timeout=timeout)
        if resp.status_code != 200:
            raise EngineError(f"HTTP {resp.status_code}")

        text = resp.text.strip()
        if text.startswith("<") or "百度安全验证" in text[:2000] or "wappass" in text[:500]:
            raise EngineError("代理仍返回验证码页（额度或出口 IP 问题）")

        import json

        try:
            data = json.loads(text)
        except Exception:
            raise EngineError("响应非 JSON（服务返回异常页）") from None

        items = _baidu_parse(data, baseline_block or [])
        return {
            "name": name,
            "status": "ok",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": items,
        }

    return search


scraperapi_search = _make_search("scraperapi", "http://api.scraperapi.com/", _SCRAPERAPI_KEY_ENV, {"country_code": "cn"})
hasdata_search = _make_search("hasdata", "https://api.hasdata.com/scrape", _HASDATA_KEY_ENV, {"country_code": "cn"})

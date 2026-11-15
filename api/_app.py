"""Yuer Search 编排层（FastAPI ASGI 应用主体）。

为什么拆文件：Vercel 的 api/ 目录按「文件名 = 路由」映射，/api/search 需要 api/search.py。
应用主体放在 _app.py（下划线开头不会被部署为独立函数），由 index.py / search.py /
health.py 三个薄入口共享同一个 app。

隐私设计（0 数据收集）：
- 不记录查询内容：任何日志/异常/响应里都不出现查询词；
- 无用户标识、无 Cookie、无第三方统计；
- 边缘缓存仅按"查询词+参数"为键缓存归一化结果（不含任何用户维度），短期过期。

快稳设计：
- 并行抓取全部启用引擎（线程池），单引擎 6s HTTP 超时、9s 编排总超时，互不拖累；
- 响应头 s-maxage 让 Vercel 边缘按查询缓存 30 分钟 + SWR 24h，重复查询零回源；
- 单引擎失败/降级不影响其他引擎结果（per-engine status 透传给前端状态条）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 本地开发读取仓库根目录 .env；Vercel 由平台注入环境变量，不读取文件。
if not os.environ.get("VERCEL"):
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        pass
    else:
        load_dotenv(_ROOT / ".env", override=False)

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from search_engines import REGISTRY, detect_lang

try:
    from search_engines import brave_enabled
except Exception:  # pragma: no cover
    brave_enabled = lambda: False  # noqa: E731

_BRAVE_ENV_FLAG = bool(os.environ.get("BRAVE_ENABLED", "").strip() == "1")
# 官方 API 类引擎的双重门禁：基线 enabled + 环境变量齐备才默认启用
_ENV_GATES = {
    "tavily": ("TAVILY_API_KEY",),
    "serper": ("SERPER_API_KEY",),
    "exa": ("EXA_API_KEY",),
    "firecrawl": ("FIRECRAWL_API_KEY",),
    "scraperapi": ("SCRAPERAPI_KEY",),
    "hasdata": ("HASDATA_KEY",),
    "brightdata": ("BRIGHTDATA_API_TOKEN",),
    "zhihu": ("ZHIHU_API_KEY",),
}
_ENGINE_ORDER = (
    "bing", "google", "ddg", "mojeek", "bilibili", "zhihu", "baidu", "marginalia",
    "brave", "tavily", "serper", "brightdata", "exa", "firecrawl",
    "scraperapi", "hasdata", "searxng",
)

_HTTP_TIMEOUT = 6.0
_TOTAL_TIMEOUT = 9.0
_CACHE_CONTROL = "public, s-maxage=1800, stale-while-revalidate=86400"

# mode 参数到引擎子集的映射（engines 参数的快捷方式；显式 engines 优先于 mode）
_MODE_ENGINES: dict[str, list[str]] = {"bing": ["bing"]}

_FALLBACK_BASELINE: dict = {
    "engines": {"ddg": {"enabled": True}, "bing": {"enabled": True}, "marginalia": {"enabled": True}},
    "pushdown": {"max_sites": 12},
}


def _load_baseline() -> dict:
    for candidate in (_ROOT / "config" / "baseline.json", _HERE.parent / "baseline.json"):
        try:
            if candidate.is_file():
                return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
    return _FALLBACK_BASELINE


BASELINE = _load_baseline()

app = FastAPI(title="Yuer Search", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "engines": sorted(REGISTRY),
            "brave_enabled": _BRAVE_ENV_FLAG,
            "baseline_loaded": bool(BASELINE),
        },
        headers={"Cache-Control": "no-store"},
    )


def _google_cx() -> str:
    return (
        os.environ.get("GOOGLE_CSE_CX")
        or os.environ.get("VITE_GOOGLE_CSE_CX")
        or ""
    ).strip()


def _engine_availability() -> dict[str, dict[str, object]]:
    """设置面板的唯一事实来源：服务端停用或缺配置的引擎不可在本端启用。"""
    conf = BASELINE.get("engines", {})
    out: dict[str, dict[str, object]] = {}
    for name in _ENGINE_ORDER:
        enabled = bool(conf.get(name, {}).get("enabled", name != "brave"))
        reason = ""
        if not enabled:
            reason = "服务端未启用"
        elif name == "brave" and not _BRAVE_ENV_FLAG:
            reason = "未启用 Brave"
        elif name == "google" and not _google_cx():
            reason = "未配置 GOOGLE_CSE_CX"
        else:
            missing = [k for k in _ENV_GATES.get(name, ()) if not os.environ.get(k, "").strip()]
            if missing:
                reason = f"未配置 {missing[0]}"
        out[name] = {"available": not reason, **({"reason": reason} if reason else {})}
    return out


def _resolve_engines(engines_param: str | None) -> list[str]:
    availability = _engine_availability()
    if engines_param:
        names = [e.strip().lower() for e in engines_param.split(",") if e.strip().lower() in REGISTRY]
    else:
        conf = BASELINE.get("engines", {})
        names = [name for name in _ENGINE_ORDER if conf.get(name, {}).get("enabled", name != "brave")]
    # 显式传入的子集也必须通过同一套服务端配置门禁
    return [name for name in names if availability.get(name, {}).get("available")]


def _run_engines(names: list[str], *, query: str, lang: str, page: int, block: list[str]) -> dict:
    out: dict[str, dict] = {}
    if not names:
        return out
    deadline = time.perf_counter() + _TOTAL_TIMEOUT - 0.5
    pool = ThreadPoolExecutor(max_workers=len(names))
    futures = {
        pool.submit(
            REGISTRY[name],
            query,
            lang=lang,
            page=page,
            baseline_block=block,
            timeout=_HTTP_TIMEOUT,
            deadline=deadline,
        ): name
        for name in names
    }
    try:
        done, pending = wait(futures, timeout=_TOTAL_TIMEOUT)
        for fut in pending:
            fut.cancel()
        for fut in done:
            name = futures[fut]
            try:
                out[name] = fut.result()
            except Exception as exc:
                # EngineError 文案受控（无查询词）；意外异常只透出类型名
                note = str(exc)[:120] if type(exc).__name__ == "EngineError" else type(exc).__name__
                out[name] = {
                    "name": name,
                    "status": "error",
                    "latency_ms": None,
                    "results": [],
                    "note": note,
                }
    finally:
        # 不等待残留线程：引擎无副作用，超时后立即返回响应（进程内残留请求自行结束）
        pool.shutdown(wait=False, cancel_futures=True)
    for name in names:
        out.setdefault(
            name,
            {
                "name": name,
                "status": "timeout",
                "latency_ms": None,
                "results": [],
                "note": f"编排层 {_TOTAL_TIMEOUT}s 超时",
            },
        )
    return out


@app.get("/api/config")
def api_config() -> JSONResponse:
    """前端运行时配置。cx 是公开值（embed 页面源码可见），经服务端注入以兼容
    Vercel 环境变量名限制（不允许 VITE_ 前缀）；同时兼容旧构建期变量名。"""
    brave = os.environ.get("BRAVE_ENABLED", "").strip() == "1"
    return JSONResponse(
        {
            "google_cse_cx": _google_cx(),
            "brave_enabled": brave,
            "engine_availability": _engine_availability(),
        },
        headers={"Cache-Control": "public, s-maxage=300"},
    )


@app.get("/api/debug/cse")
def debug_cse(q: str = Query("vue3", max_length=100)) -> JSONResponse:
    """诊断端点：转储 CSE element/v1 原始响应（格式逆向用；响应内容本身是公开搜索结果）。"""
    from search_engines import cse

    try:
        raw = cse.fetch_raw(q.strip(), lang="en", page=1, timeout=6.0)
    except Exception as exc:
        return JSONResponse(
            {"fetch_error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            headers={"Cache-Control": "no-store"},
        )
    parsed = None
    full = raw.get("body_full")
    if full:
        data = cse._parse_payload(full)
        parsed = cse._extract_results(data, [])[:3] if data else None
    return JSONResponse(
        {"raw": {k: v for k, v in raw.items() if k != "body_full"}, "parsed_sample": parsed},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/debug/raw")
def debug_raw(
    engine: str = Query(...),
    q: str = Query("test", max_length=100),
    target: str = Query("baidu"),
    df: str | None = Query(None),
    fmt: str = Query("json"),
    country: str | None = Query(None),
    brd_json: str | None = Query(None),
) -> JSONResponse:
    """通用原始响应转储：仅支持实现了 fetch_raw 的引擎（brightdata/cse）。"""
    import importlib

    module_map = {"brightdata": "search_engines.brightdata", "cse": "search_engines.cse"}
    mod_path = module_map.get(engine)
    if not mod_path:
        return JSONResponse({"error": f"engine {engine} 无 fetch_raw"}, headers={"Cache-Control": "no-store"})
    mod = importlib.import_module(mod_path)
    if not hasattr(mod, "fetch_raw"):
        return JSONResponse({"error": "module missing fetch_raw"}, headers={"Cache-Control": "no-store"})
    try:
        raw = mod.fetch_raw(
            q.strip(),
            lang="zh" if engine == "brightdata" else "en",
            page=1,
            timeout=25.0,
            target=target,
            data_format=df,
            fmt=fmt,
            country=country,
            brd_json=brd_json == "1",
        )
    except Exception as exc:
        return JSONResponse({"fetch_error": f"{type(exc).__name__}: {str(exc)[:200]}"}, headers={"Cache-Control": "no-store"})
    parsed = None
    diag: dict = {}
    full = raw.get("body_full") or raw.get("body_head") or ""
    try:
        if hasattr(mod, "_parse_payload"):
            data = mod._parse_payload(full)
            if data:
                parsed = mod._extract_results(data, [])[:3]
        elif hasattr(mod, "_extract_list") and full.strip().startswith("{"):
            import json as _json

            wrapper = _json.loads(full)
            body = wrapper.get("body", "") if isinstance(wrapper, dict) else ""
            diag["wrapper_keys"] = list(wrapper.keys())[:8] if isinstance(wrapper, dict) else None
            diag["body_kind"] = "json" if body.strip().startswith("{") else ("html" if body.strip().startswith("<") else "other")
            diag["body_len"] = len(body)
            if body.strip().startswith("{"):
                inner = _json.loads(body)
                diag["inner_keys"] = list(inner.keys())[:10]
                for key in ("organic", "results"):
                    if isinstance(inner.get(key), list):
                        diag[f"{key}_count"] = len(inner[key])
                        diag[f"{key}_sample"] = [
                            {k: str(v)[:44] for k, v in row.items() if k in ("title", "url", "link", "description", "pos")}
                            for row in inner[key][:2]
                        ]
            parsed = None
    except Exception as exc:
        diag = {"diag_error": str(exc)[:120]}
    return JSONResponse(
        {"raw": {k: v for k, v in raw.items() if k != "body_full"}, "parsed_sample": parsed, "diag": diag},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/debug/searxng")
def debug_searxng(
    q: str = Query("test", max_length=60),
    instances: str | None = Query(None, max_length=4000),
) -> JSONResponse:
    """运维探针：逐实例实测 format=json 开放性（从当前函数出口发起，并行）。

    ?instances=a,b,c 可覆盖实例清单（用于全量探测外部清单）；
    结果里 verdict=OPEN 的实例可直接填入 SEARXNG_INSTANCES 环境变量。
    """
    from search_engines import searxng

    override = [u.strip().rstrip("/") for u in instances.split(",") if u.strip()] if instances else None
    try:
        report = searxng.probe_instances(q.strip() or "test", instances_override=override, timeout=6.0, limit=40)
    except Exception as exc:
        return JSONResponse(
            {"probe_error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(report, headers={"Cache-Control": "no-store"})


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=200),
    page: int = Query(1, ge=1, le=10),
    engines: str | None = Query(None),
    mode: str | None = Query(None),
    pushdown: int | None = Query(None, ge=0, le=25),
    lang: str | None = Query(None),
) -> JSONResponse:
    started = time.perf_counter()
    query = q.strip()
    if not query:
        return JSONResponse({"error": "empty query"}, status_code=400, headers={"Cache-Control": "no-store"})

    # lang 可被请求参数覆盖（auto|zh|en），默认按查询内容自动检测
    lang = lang if lang in ("zh", "en") else detect_lang(query)
    block_all = [d for d in BASELINE.get("domains", {}).get("block", []) if isinstance(d, str)]
    # pushdown 数量可被请求参数覆盖（运维诊断用：0 = 不下推）
    max_sites = int(pushdown) if pushdown is not None else int(
        BASELINE.get("pushdown", {}).get("max_sites", 12)
    )
    # mode=bing 是 engines=bing 的快捷方式；显式 engines 参数优先
    engines_param = engines if engines else ",".join(_MODE_ENGINES.get(mode or "", []))
    requested = _resolve_engines(engines_param)
    engine_results = _run_engines(
        requested, query=query, lang=lang, page=page, block=block_all[:max_sites]
    )

    payload = {
        "query": query,
        "lang": lang,
        "page": page,
        "engines": [engine_results[name] for name in requested if name in engine_results],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    return JSONResponse(payload, headers={"Cache-Control": _CACHE_CONTROL})

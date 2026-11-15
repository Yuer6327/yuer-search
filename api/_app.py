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

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from search_engines import REGISTRY, detect_lang

try:
    from search_engines import brave_enabled
except Exception:  # pragma: no cover
    brave_enabled = lambda: False  # noqa: E731

_BRAVE_ENV_FLAG = bool(os.environ.get("BRAVE_ENABLED", "").strip() == "1")

_HTTP_TIMEOUT = 6.0
_TOTAL_TIMEOUT = 9.0
_CACHE_CONTROL = "public, s-maxage=1800, stale-while-revalidate=86400"

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


def _resolve_engines(engines_param: str | None) -> list[str]:
    conf = BASELINE.get("engines", {})
    if engines_param:
        names = [e.strip().lower() for e in engines_param.split(",") if e.strip().lower() in REGISTRY]
    else:
        names = [
            name
            for name in ("ddg", "bing", "marginalia", "brave")
            if conf.get(name, {}).get("enabled", name != "brave")
        ]
    # Brave 双重门禁：基线 enabled + 环境变量
    if "brave" in names and not (_BRAVE_ENV_FLAG and conf.get("brave", {}).get("enabled")):
        names.remove("brave")
    return names


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
    cx = (
        os.environ.get("GOOGLE_CSE_CX")
        or os.environ.get("VITE_GOOGLE_CSE_CX")
        or ""
    ).strip()
    brave = os.environ.get("BRAVE_ENABLED", "").strip() == "1"
    return JSONResponse(
        {"google_cse_cx": cx, "brave_enabled": brave},
        headers={"Cache-Control": "public, s-maxage=300"},
    )


@app.get("/api/search")
def api_search(
    q: str = Query(..., min_length=1, max_length=200),
    page: int = Query(1, ge=1, le=10),
    engines: str | None = Query(None),
) -> JSONResponse:
    started = time.perf_counter()
    query = q.strip()
    if not query:
        return JSONResponse({"error": "empty query"}, status_code=400, headers={"Cache-Control": "no-store"})

    lang = detect_lang(query)
    block_all = [d for d in BASELINE.get("domains", {}).get("block", []) if isinstance(d, str)]
    max_sites = int(BASELINE.get("pushdown", {}).get("max_sites", 12))
    requested = _resolve_engines(engines)
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

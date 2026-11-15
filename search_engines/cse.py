"""Google CSE 服务端中继引擎：从服务器出口取 Google 结果，大陆直连用户无需本机能访问 Google。

原理：CSE embed 控件（浏览器端免费、无额度限制的那个）内部走 cse.google.com/cse/element/v1
端点获取结果。本引擎在服务端请求同一端点并解析为标准结果——Google 结果由此成为聚合管线里
的一个普通引擎（可加权、可被用户开关）。

风险与护栏：
- element/v1 是未公开端点，返回格式可能随 Google 改版漂移 → 解析失败自动降级，不影响其他引擎；
- 与 Bing 同样适用相关性护栏（零词元重叠即判投毒/异常，丢弃并附样本）；
- cx 从环境变量 GOOGLE_CSE_CX（兼容 VITE_GOOGLE_CSE_CX）读取，未配置则跳过。
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import time

from .http import http_session
from .util import EngineError, apply_pushdown, domain_of, host_matches
from .util import relevance_tokens as _tokenize  # noqa: F401  与 bing 同款词元

_CX_ENVS = ("GOOGLE_CSE_CX", "VITE_GOOGLE_CSE_CX")
_ENDPOINT = "https://cse.google.com/cse/element/v1"
_MAX_RESULTS = 12


def get_cx() -> str:
    for key in _CX_ENVS:
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return ""


def is_enabled() -> bool:
    return bool(get_cx())


def fetch_raw(query: str, *, lang: str = "en", page: int = 1, timeout: float = 6.0) -> dict:
    """诊断矩阵：多变体探测 element/v1 在服务器出口的可用性与响应格式。"""
    cx = get_cx()
    if not cx:
        return {"error": "GOOGLE_CSE_CX 未设置"}
    start = (page - 1) * 10 + 1
    base_params = {
        "cx": cx,
        "q": query,
        "num": "10",
        "start": str(start),
        "hl": "zh-CN" if lang == "zh" else "en",
        "safe": "active",
    }

    out: dict = {"variants": []}
    session = http_session()
    # 预热：访问 CSE 宿主页拿 Cookie
    try:
        r0 = session.get(f"https://cse.google.com/cse?cx={cx}", timeout=5.0)
        out["warmup"] = {"status": r0.status_code, "bytes": len(r0.text)}
    except Exception as exc:
        out["warmup"] = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    variants = {
        "element_full": (f"{_ENDPOINT}", {**base_params, "cseclient": "host"}),
        "element_minimal": (f"{_ENDPOINT}", {"cx": cx, "q": query}),
        "element_jsonp": (f"{_ENDPOINT}", {**base_params, "callback": "google.search.cse.api0.render"}),
        "element_v2": (f"https://cse.google.com/cse/element/v2", {**base_params, "cseclient": "host"}),
        "element_gapis": (f"https://cse.googleapis.com/cse/element/v1", {**base_params, "cseclient": "host"}),
        "public_page": (f"https://cse.google.com/cse?cx={cx}&q={query}", {}),
    }
    for name, (url, params) in variants.items():
        t0 = time.perf_counter()
        try:
            resp = session.get(
                url,
                params=params or None,
                timeout=timeout,
                headers={"Referer": f"https://cse.google.com/cse?cx={cx}"},
            )
            body = resp.text
            out["variants"].append(
                {
                    "name": name,
                    "status": resp.status_code,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "bytes": len(body),
                    "head": body[:400],
                    "has_result_links": bool(re.search(r'class="(?:gs_|gsc-)', body)) or "results" in body[:5000].lower(),
                }
            )
        except Exception as exc:
            out["variants"].append(
                {"name": name, "error": f"{type(exc).__name__}: {str(exc)[:120]}", "latency_ms": int((time.perf_counter() - t0) * 1000)}
            )
    return out


def _clean(text: str | None) -> str:
    """去 HTML 标签（<b> 高亮等）并反转义实体。"""
    if not text:
        return ""
    return html_lib.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _parse_payload(text: str) -> dict | None:
    """剥掉 Google 的防劫持前缀（/*O*/、)]}' 等）后解析 JSON。"""
    t = text.strip()
    if t.startswith("/*"):
        end = t.find("*/")
        if end != -1:
            t = t[end + 2 :]
    if t.startswith(")]}'"):
        t = t[4:]
    t = t.strip()
    try:
        data = json.loads(t)
    except Exception:
        return None
    if isinstance(data, list) and data:
        data = data[-1] if isinstance(data[-1], dict) else {}
    return data if isinstance(data, dict) else None


def _extract_results(data: dict, blocked: list[str]) -> list[dict]:
    raw_results = data.get("results") or []
    items: list[dict] = []
    seen: set[str] = set()
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        url = r.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        title = _clean(r.get("titleNoFormatting") or r.get("title") or url)
        snippet = _clean(r.get("content") or r.get("snippet") or "")
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "domain": domain, "snippet": snippet})
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
    cx = get_cx()
    if not cx:
        return {
            "name": "google",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 GOOGLE_CSE_CX",
        }

    blocked = baseline_block or []
    q = apply_pushdown(query, blocked)
    params = {
        "cx": cx,
        "q": q,
        "num": "10",
        "start": str((page - 1) * 10 + 1),
        "hl": "zh-CN" if lang == "zh" else "en",
        "safe": "active",
        "cseclient": "host",
    }
    session = http_session()
    try:
        session.get(f"https://cse.google.com/cse?cx={cx}", timeout=4.0)
    except Exception:
        pass  # 预热失败不阻塞主流程
    resp = session.get(
        _ENDPOINT,
        params=params,
        timeout=timeout,
        headers={"Referer": f"https://cse.google.com/cse?cx={cx}"},
    )
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = _parse_payload(resp.text)
    if data is None:
        # 格式漂移：响应不是可解析 JSON —— 明确降级（样本便于诊断）
        return {
            "name": "google",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "CSE 端点响应格式无法解析（可能 Google 改版）",
            "discarded_sample": [resp.text[:120]],
        }

    items = _extract_results(data, blocked)

    # 相关性护栏（与 Bing 同款）：零词元重叠 → 异常响应，丢弃
    tokens = _tokenize(query)
    if items and tokens:
        has_overlap = any(
            any(t in (r["title"] + " " + r["snippet"]).lower() for t in tokens) for r in items
        )
        if not has_overlap:
            return {
                "name": "google",
                "status": "degraded",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "results": [],
                "note": "相关性校验未通过：CSE 端点返回无关结果，已丢弃",
                "discarded_sample": [i["title"][:80] for i in items[:3]],
            }

    return {
        "name": "google",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }


def _tokenize_unused_placeholder() -> None:  # pragma: no cover
    """词元逻辑已迁移至 util.relevance_tokens（见模块顶部别名）。"""

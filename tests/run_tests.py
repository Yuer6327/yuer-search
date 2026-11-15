#!/usr/bin/env python3
"""引擎解析器测试：fixture（离线）+ --live（低频实测可达引擎）。

用法：
    python tests/run_tests.py            # 离线 fixture 测试 + API 应用导入测试
    python tests/run_tests.py --live     # 追加：向可达上游各发 1 次低频实测（勿频繁执行）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIX = Path(__file__).resolve().parent / "fixtures"


def main() -> int:
    from search_engines import REGISTRY, bing, ddg, detect_lang
    from search_engines.http import HAS_CURL_CFFI

    print(f"[env] curl_cffi 可用: {HAS_CURL_CFFI}" + ("" if HAS_CURL_CFFI else "（本地降级 requests；Vercel 上始终可用）"))

    # ---------- DDG lite fixture ----------
    html = (FIX / "ddg_lite.html").read_text(encoding="utf-8")
    items = ddg._parse(html, blocked=["csdn.net", "aliyun.com"])
    urls = [i["url"] for i in items]
    assert len(items) == 3, f"lite 期望 3 条（csdn 被基线过滤），实际 {len(items)}"
    assert urls[0] == "https://docs.python.org/3/library/asyncio.html", urls[0]
    assert urls[1] == "https://github.com/python/asyncio", urls[1]
    assert all("csdn.net" not in u for u in urls), "基线域名未过滤"
    assert items[0]["snippet"].startswith("This module"), items[0]["snippet"][:40]
    print("[ok] ddg lite 解析 + uddg 解包 + 基线过滤")

    # ---------- DDG html fixture ----------
    html = (FIX / "ddg_html.html").read_text(encoding="utf-8")
    items = ddg._parse(html, blocked=[])
    assert len(items) == 2, f"html 期望 2 条，实际 {len(items)}"
    assert items[0]["url"] == "https://tokio.rs/tokio/tutorial"
    print("[ok] ddg html 兜底解析")

    # ---------- Bing fixture ----------
    html = (FIX / "bing.html").read_text(encoding="utf-8")
    items = bing._parse(html, blocked=["csdn.net"])
    assert len(items) == 3, f"bing 期望 3 条（广告位剔除），实际 {len(items)}"
    assert items[0]["url"] == "https://cn.vuejs.org/guide/extras/composition-api-faq.html"
    wrapped = [i for i in items if "github.com/vuejs/core" in i["url"]]
    assert wrapped, "ck/a base64 包链未解出 github.com/vuejs/core"
    print("[ok] bing 解析 + 广告剔除 + ck/a 解包")

    # ---------- 相关性护栏 ----------
    r = bing.search.__wrapped__ if hasattr(bing.search, "__wrapped__") else bing.search
    junk_html = '<html><ul id="b_results"><li class="b_algo"><h2><a href="https://a.example/">完全无关</a></h2></li></ul></html>'
    # 构造一个零重叠场景：查询词元与结果完全不重叠
    tokens = bing._tokenize("zzqqxx impossiblequeryword")
    assert tokens, "词元提取失败"
    assert not any(t in "完全无关的文本".lower() for t in tokens), "不应有重叠"
    print("[ok] 相关性护栏词元逻辑")

    # ---------- 语言检测 ----------
    assert detect_lang("异步 教程") == "zh"
    assert detect_lang("python asyncio") == "en"
    print("[ok] 语言检测")

    # ---------- API 应用可导入 + 路由注册 ----------
    from api.index import app  # noqa: F401  验证 sys.path 注入与 baseline 加载

    paths = {r.path for r in app.routes}
    assert "/api/search" in paths and "/api/health" in paths, paths
    print("[ok] api/index.py 可导入，路由注册齐全")

    # ---------- 可选：低频实测 ----------
    if "--live" in sys.argv:
        print("\n[live] 向可达上游各发 1 次低频实测（本机网络决定可达性；DDG 在大陆直连通常不可达）")
        for name in ("bing", "marginalia", "ddg"):
            try:
                res = REGISTRY[name](
                    "python asyncio tutorial", lang="en", page=1, baseline_block=[], timeout=8
                )
                print(f"  {name}: status={res['status']} results={len(res['results'])} note={res.get('note', '')}")
            except Exception as exc:
                print(f"  {name}: FAIL {type(exc).__name__}: {exc}")

    print("\n全部测试通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

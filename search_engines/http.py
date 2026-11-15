"""共享 HTTP 客户端：优先 curl_cffi（Chrome TLS 指纹伪装），不可用时退回 requests。

TLS 指纹伪装是从数据中心 IP（Vercel 函数）抓取 DDG/Brave 的关键护栏；
Bing/Marginalia 对普通指纹宽容，但统一走伪装客户端无害。
"""
from __future__ import annotations

import os
import shutil
import tempfile

try:
    from curl_cffi import requests as _impl

    HAS_CURL_CFFI = True
except Exception:  # pragma: no cover —— 本地环境缺 wheel 时降级（Vercel 上始终可用）
    import requests as _impl  # type: ignore

    HAS_CURL_CFFI = False

try:
    import certifi as _certifi
except Exception:  # pragma: no cover
    _certifi = None  # type: ignore[assignment]

CHROME_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="133", "Not(A:Brand";v="24", "Google Chrome";v="133"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def http_session():
    """带 Cookie 的会话（预热的 Chrome 指纹）：搜索引擎的反爬普遍依赖 Cookie 存在性。"""
    if HAS_CURL_CFFI:
        return _impl.Session(impersonate="chrome")
    return _impl.Session()  # type: ignore[return-value]

_VERIFY_PATH: str | None = None


def _safe_verify() -> str | None:
    """curl-impersonate 在含非 ASCII 字符的 CAfile 路径上加载失败（curl error 77）。

    典型场景：Windows 本地开发、项目放在含中文/空格的目录里。把 certifi 证书
    复制到 ASCII 临时路径后通过 verify 传入即可绕过；Linux（Vercel）不受影响。
    """
    global _VERIFY_PATH
    if _certifi is None:
        return None
    if _VERIFY_PATH is not None:
        return _VERIFY_PATH
    src = _certifi.where()
    try:
        src.encode("ascii")
        return None  # ASCII 路径，走默认行为
    except UnicodeEncodeError:
        pass
    try:
        dst = os.path.join(tempfile.gettempdir(), "yuer-search-cacert.pem")
        shutil.copyfile(src, dst)
        _VERIFY_PATH = dst
        return dst
    except Exception:
        return None


def http_get(url: str, *, headers: dict | None = None, timeout: float = 6.0, params: dict | None = None):
    kwargs: dict = {"headers": {**CHROME_HEADERS, **(headers or {})}, "timeout": timeout}
    if params:
        kwargs["params"] = params
    if HAS_CURL_CFFI:
        kwargs["impersonate"] = "chrome"
        verify = _safe_verify()
        if verify:
            kwargs["verify"] = verify
    return _impl.get(url, **kwargs)

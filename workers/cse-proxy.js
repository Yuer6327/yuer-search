/**
 * Google CSE 反代（服务端中继的出口 IP 换乘）：
 *   Vercel 函数 → 本 Worker → cse.google.com
 * 把 element/v1 的来源 IP 从 Vercel 机房换成 Cloudflare 边缘，绕开 Google 对云 IP 的定向丢弃
 * （Vercel 出口实测：预热/Cookie/参数变体全部黑洞，证据见 /api/debug/cse）。
 *
 * 协议：路径镜像（透明反代）—— /cse/element/v1?... 原样转发到
 * https://cse.google.com/cse/element/v1?...，请求头/响应头（含 Set-Cookie）透传，
 * 引擎侧（search_engines/cse.py）只需换基地址，预热拿 Cookie 的流程不受影响。
 *
 * 安全：仅放行 /cse* 路径且上游主机固定 cse.google.com，防止被当开放代理滥用；
 * 响应附加 CORS 头（公开搜索结果），将来浏览器直连的 Google 模式也可复用。
 *
 * 部署（二选一）：
 * 1. Cloudflare 控制台：Workers & Pages → Create Worker → 粘贴本文件 → Deploy；
 * 2. wrangler：npx wrangler deploy workers/cse-proxy.js --name cse-proxy
 * 部署后在 Vercel 设 GOOGLE_CSE_PROXY_URL=https://<name>.<account>.workers.dev 并 Redeploy，
 * 用 /api/debug/cse 验证 variants 返回 200 且有结果后，再打开 baseline.json 的 google 引擎。
 *
 * 注意：*.workers.dev 在大陆被墙——本 Worker 只供服务端调用（Vercel→CF 边缘），不受影响；
 * 若要给浏览器直连的 Google 模式复用（大陆用户免梯），需在 CF 给自有域名加 Workers 路由。
 */

const UPSTREAM = "https://cse.google.com";

// 从入站请求转发的头（User-Agent 保持 Chrome 指纹；Cookie 透传让预热 Cookie 流程继续生效）
const FORWARD_HEADERS = ["user-agent", "accept", "accept-language", "cookie"];

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors() });
    }
    if (request.method !== "GET") {
      return new Response("method not allowed", { status: 405, headers: cors() });
    }

    const url = new URL(request.url);
    if (!url.pathname.startsWith("/cse")) {
      return new Response("only /cse* paths are proxied", { status: 403, headers: cors() });
    }

    const headers = new Headers();
    for (const name of FORWARD_HEADERS) {
      const v = request.headers.get(name);
      if (v) headers.set(name, v);
    }
    // Google 校验 element/v1 请求的 Referer 必须来自 CSE 宿主页（无则按 cx 参数构造）
    const referer = request.headers.get("referer");
    if (referer && referer.includes("cse.google.com")) {
      headers.set("Referer", referer);
    } else {
      const cx = url.searchParams.get("cx");
      headers.set("Referer", `https://cse.google.com/cse${cx ? `?cx=${cx}` : ""}`);
    }
    if (!headers.has("User-Agent")) {
      headers.set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36");
    }

    const res = await fetch(UPSTREAM + url.pathname + url.search, {
      method: request.method,
      headers,
      redirect: "follow",
    });

    const out = cors();
    const contentType = res.headers.get("content-type");
    if (contentType) out["Content-Type"] = contentType;
    // Set-Cookie 逐条透传（多值头不能走普通 Headers.get）
    for (const sc of setCookiesOf(res)) out.append("Set-Cookie", sc);
    return new Response(res.body, { status: res.status, headers: out });
  },
};

function setCookiesOf(res) {
  try {
    return res.headers.getAll("set-cookie") ?? [];
  } catch {
    const single = res.headers.get("set-cookie");
    return single ? [single] : [];
  }
}

function cors() {
  return new Headers({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Cache-Control": "no-store",
  });
}

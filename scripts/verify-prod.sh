#!/usr/bin/env bash
# 生产环境自检：每次部署完成后 ~90s 运行，逐项检查并汇总 PASS/FAIL。
# 用法：bash scripts/verify-prod.sh [BASE_URL]   （默认 https://s.yuer6327.top）
set -u

BASE_URL="${1:-${BASE_URL:-https://s.yuer6327.top}}"
PASS=0
FAIL=0

ok() { echo "PASS  $1"; PASS=$((PASS + 1)); }
bad() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }
note() { echo "NOTE  $1"; }

code_of() { curl -sS -o /dev/null -w '%{http_code}' -m 30 "$1" 2>/dev/null || echo 000; }

echo "=== Yuer Search 生产自检：$BASE_URL ==="

c=$(code_of "$BASE_URL/")
[ "$c" = "200" ] && ok "首页 / → 200" || bad "首页 / → $c"

h=$(curl -sS -m 30 "$BASE_URL/api/health" 2>/dev/null)
case "$h" in
  *'"ok":true'*) ok "/api/health → ok=true" ;;
  *) bad "/api/health → ${h:0:160}" ;;
esac

cf=$(curl -sS -m 30 "$BASE_URL/api/config" 2>/dev/null)
case "$cf" in
  *google_cse_cx*) ok "/api/config 返回 cx 配置" ;;
  *) bad "/api/config → ${cf:0:160}" ;;
esac

NONCE="$(date +%s)"
# 金丝雀查询用已在生产验证稳定的常规词（单 token 带数字的冷门词会被 Bing 投毒，属已知降级场景）
s1=$(curl -sS -m 30 "$BASE_URL/api/search?q=rust%20async%20tutorial&engines=bing&_=$NONCE" 2>/dev/null)
case "$s1" in
  *'"status":"ok"'*) ok "快速通道（bing）→ ok" ;;
  *) bad "快速通道（bing）→ ${s1:0:220}" ;;
esac

# 纯 Bing 单引擎模式：mode=bing 应等价 engines=bing，且只返回 bing 一个引擎
s3=$(curl -sS -m 30 "$BASE_URL/api/search?q=rust%20async%20tutorial&mode=bing&_=$NONCE" 2>/dev/null)
case "$s3" in
  *'"status":"ok"'*) ok "单引擎模式（mode=bing）→ ok" ;;
  *) bad "单引擎模式（mode=bing）→ ${s3:0:220}" ;;
esac
echo "$s3" | grep -q '"name":"bing"' && ! echo "$s3" | grep -qE '"name":"(ddg|marginalia)"' \
  && ok "mode=bing 引擎清单仅含 bing" || bad "mode=bing 引擎清单异常"

# 知乎引擎：生产需配置 ZHIHU_API_KEY，skipped 视为密钥缺失（sync 失效）
s4=$(curl -sS -m 30 "$BASE_URL/api/search?q=rave%20%E6%96%87%E5%8C%96&engines=zhihu&_=$NONCE" 2>/dev/null)
case "$s4" in
  *'"status":"ok"'*) ok "知乎引擎（zhihu）→ ok" ;;
  *'"status":"skipped"'*) bad "知乎引擎（zhihu）→ skipped（生产缺 ZHIHU_API_KEY？）" ;;
  *) bad "知乎引擎（zhihu）→ ${s4:0:220}" ;;
esac

# SPA 路由 /search 必须经 rewrite 兜底回 index.html（浏览器搜索词 URL）
c2=$(code_of "$BASE_URL/search?q=canary&mode=bing")
[ "$c2" = "200" ] && ok "SPA 路由 /search → 200" || bad "SPA 路由 /search → $c2"

s2=$(curl -sS -m 45 "$BASE_URL/api/search?q=rust%20async%20tutorial&_=$NONCE" 2>/dev/null)
case "$s2" in
  *'"status":"ok"'*) ok "全量聚合 → ok" ;;
  *) bad "全量聚合 → ${s2:0:200}" ;;
esac
echo "$s2" | grep -q '"status":"timeout"' && note "全量聚合含超时引擎（DDG/Marginalia 在云 IP 上属常态）"
echo "$s2" | grep -q '"status":"degraded"' && note "全量聚合含降级引擎（护栏丢弃静默垃圾，属正常防护）"

curl -sS -o /dev/null -m 30 "$BASE_URL/" 2>/dev/null # 先预热一次
v=$(curl -sS -o /dev/null -D - -m 30 "$BASE_URL/" 2>/dev/null | grep -i '^x-vercel-cache:' | tr -d '\r' | awk '{print $2}')
case "$v" in
  HIT) ok "首页边缘缓存 → HIT" ;;
  *) bad "首页边缘缓存 → ${v:-NONE}" ;;
esac

echo "-----"
echo "结果：通过 $PASS，失败 $FAIL"
[ "$FAIL" = "0" ] || exit 1

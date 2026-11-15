#!/usr/bin/env bash
# Vercel 缓存预热：拉 sitemap 全站 URL，并发 curl 预热边缘缓存，统计 X-Vercel-Cache 命中率
# 配套工作流：.github/workflows/cache-hit-check.yml
# 来源：vercel-optimize 技能模板（BASE_URL 已适配 s.yuer6327.top）
#
# ⚠️ 不要给这里的 curl 加 Cache-Control: no-cache 请求头：
#    curl 没有客户端缓存，加了反而强制边缘重新验证，全部测成 MISS
set -u -o pipefail

BASE_URL="${BASE_URL:-https://example.com}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-30}"
PARALLEL="${PARALLEL:-8}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-20}"
RESOLVE_IP="${RESOLVE_IP:-}" # 例：76.76.21.21（域名前置 CF 时直打 Vercel 边缘）
HIT_TARGET="${HIT_TARGET:-95}"
MAX_CYCLES="${MAX_CYCLES:-5}"

for variable_name in INTERVAL_SECONDS PARALLEL REQUEST_TIMEOUT HIT_TARGET MAX_CYCLES; do
  if [[ ! "${!variable_name}" =~ ^[0-9]+$ ]]; then
    echo "::error::${variable_name} 必须是非负整数"
    exit 1
  fi
done

HOST="$(printf '%s' "$BASE_URL" | sed -E 's#^https?://([^/]+).*#\1#')"
RESOLVE_FLAG=""
if [ -n "$RESOLVE_IP" ]; then
  RESOLVE_FLAG="--resolve ${HOST}:443:${RESOLVE_IP}"
  echo "🌐 强制解析到 ${RESOLVE_IP}"
fi

warm_url() {
  local url="$1"
  local header_file metric http_code response_time remote_ip cache_status age_seconds

  header_file="$(mktemp)"
  # $RESOLVE_FLAG 有意不加引号：为空时不传参，非空时是单个单词
  metric="$(curl -sS -o /dev/null -m "$REQUEST_TIMEOUT" $RESOLVE_FLAG -D "$header_file" \
    -w '%{http_code}\t%{time_total}\t%{remote_ip}' "$url" 2>/dev/null || true)"
  IFS=$'\t' read -r http_code response_time remote_ip <<<"$metric"

  cache_status="$(awk 'tolower($0) ~ /^x-vercel-cache:/ {
      value = $0; sub(/^[^:]*:[[:space:]]*/, "", value); sub(/\r$/, "", value); print value
    }' "$header_file" | tail -n 1)"
  if [ -z "$cache_status" ]; then
    cache_status="$(awk 'tolower($0) ~ /^cf-cache-status:/ {
      value = $0; sub(/^[^:]*:[[:space:]]*/, "", value); sub(/\r$/, "", value); print value
    }' "$header_file" | tail -n 1)"
  fi
  age_seconds="$(awk 'tolower($0) ~ /^age:/ {
      value = $0; sub(/^[^:]*:[[:space:]]*/, "", value); sub(/\r$/, "", value)
      if (value ~ /^[0-9]+$/) print value
    }' "$header_file" | tail -n 1)"

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$url" "${http_code:-000}" "${response_time:-0.000000}" \
    "${remote_ip:-unknown}" "${cache_status:-NONE}" "${age_seconds:-}"
  rm -f "$header_file"
}

# 先初始化，sitemap 首轮失败时也不会引用到未定义变量
requested=0 successful=0 hits=0 hit_rate=0
cycle=0
metrics_file="$(mktemp)"
trap 'rm -f "$metrics_file" urls.txt' EXIT

echo "🎯 目标 HIT 率 ${HIT_TARGET}%（最多 ${MAX_CYCLES} 轮）"

while [ "$cycle" -lt "$MAX_CYCLES" ]; do
  cycle=$((cycle + 1))
  cycle_start="$(date +%s)"

  if curl -fsS --retry 2 --retry-delay 2 -m 30 $RESOLVE_FLAG "${BASE_URL}/sitemap.xml" |
    grep -oP '(?<=<loc>)[^<]+' | sed 's/\r$//' >urls.txt; then

    # ↓↓↓ 补充 sitemap 覆盖不到的 URL（每行一个完整 URL，按站点需要改）↓↓↓
    printf '%s\n' "${BASE_URL}/" >>urls.txt

    sort -u urls.txt -o urls.txt
    requested=$(wc -l <urls.txt)

    export -f warm_url
    export REQUEST_TIMEOUT RESOLVE_FLAG
    xargs -P "$PARALLEL" -I {} bash -c 'warm_url "$@"' _ {} \
      <urls.txt >"$metrics_file" || true

    summary="$(awk -F '\t' '
      {
        total++
        code=$2 + 0
        if (code >= 200 && code < 400) successful++
        response_sum += $3 + 0
        ip=($4 == "" ? "unknown" : $4)
        status=($5 == "" ? "NONE" : $5)
        if (status == "HIT") hits++
        if ($6 ~ /^[0-9]+$/) {
          age = $6 + 0
          age_total += age
          age_count++
          if (!age_seen || age < age_min) age_min = age
          if (!age_seen || age > age_max) age_max = age
          age_seen = 1
        }
      }
      END {
        average=total ? response_sum / total : 0
        hit_rate=total ? hits * 100 / total : 0
        age_average=age_count ? age_total / age_count : 0
        if (age_count)
          printf "%d\t%d\t%.3f\t%d\t%.1f\t%.0f\t%d\t%d", total, successful, average, hits, hit_rate, age_average, age_min, age_max
        else
          printf "%d\t%d\t%.3f\t%d\t%.1f\t-1\t-1\t-1", total, successful, average, hits, hit_rate
      }' "$metrics_file")"
    IFS=$'\t' read -r requested successful average_response hits hit_rate age_average age_min age_max <<<"$summary"

    ip_summary="$(awk -F '\t' '{print ($4 == "" ? "unknown" : $4)}' "$metrics_file" |
      sort | uniq -c |
      awk '{printf "%s%s(%s)", separator, $2, $1; separator=", "}')"
    status_summary="$(awk -F '\t' '{print ($5 == "" ? "NONE" : $5)}' "$metrics_file" |
      sort | uniq -c |
      awk '{printf "%s%s=%s", separator, $2, $1; separator=", "}')"

    elapsed=$(($(date +%s) - cycle_start))
    if [ "$age_average" -ge 0 ]; then
      age_summary="avg=${age_average%.*}s/min=${age_min}s/max=${age_max}s"
    else
      age_summary="N/A"
    fi

    line="[$(date '+%Y-%m-%d %H:%M:%S')] 第 $cycle 轮：预热 $requested 个页面，用时 ${elapsed}s，成功 $successful/$requested，平均响应 ${average_response}s，IP ${ip_summary:-unknown}，状态 ${status_summary:-NONE}，命中 HIT ${hits}/${requested}(${hit_rate}%)，Age ${age_summary}"
    echo "$line"
    [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$line" >>"$GITHUB_STEP_SUMMARY"
  else
    echo "::warning::[$(date '+%Y-%m-%d %H:%M:%S')] 获取 sitemap 失败，本轮跳过"
  fi

  # 达到目标命中率即停
  if [ "$requested" -gt 0 ]; then
    hit_pct="${hit_rate%%.*}"
    if [ "$hit_pct" -ge "$HIT_TARGET" ]; then
      echo "✅ HIT 率 ${hit_rate}% ≥ 目标 ${HIT_TARGET}%，预热完成"
      break
    else
      echo "⏳ HIT 率 ${hit_rate}% < 目标 ${HIT_TARGET}%，继续下一轮..."
    fi
  fi

  # 达到最大轮数则退出
  if [ "$cycle" -ge "$MAX_CYCLES" ]; then
    echo "⚠️ 已达最大轮数 ${MAX_CYCLES}，当前 HIT 率 ${hit_rate}%"
    break
  fi

  sleep "$INTERVAL_SECONDS"
done

echo "预热结束：共执行 $cycle 轮，最终 HIT 率 ${hit_rate}%"

# 逐 URL 明细报告；想留档可在工作流里启用"提交 HIT.txt"可选步骤
if [ "$requested" -gt 0 ]; then
  {
    echo "# 缓存命中报告"
    echo "- 时间：$(date '+%Y-%m-%d %H:%M:%S')"
    echo "- 站点：${BASE_URL}"
    echo "- 结果：共 $cycle 轮，HIT ${hits}/${requested}（${hit_rate}%）"
    echo
    printf 'URL\t状态\tHTTP\t耗时(s)\t边缘IP\tAge(s)\n'
    awk -F '\t' '{printf "%s\t%s\t%s\t%s\t%s\t%s\n", $1, $5, $2, $3, $4, $6}' "$metrics_file" |
      sort -t $'\t' -k2,2 -k1,1
  } >HIT.txt
  echo "📄 明细已写入 HIT.txt"
fi

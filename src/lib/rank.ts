/**
 * 融合排序：score = 引擎权重 × 域名调整 × 位置衰减，按归一化 URL 去重合并。
 * 权重模型借鉴 mat-1/metasearch2（CC0）；域名调整 = 全局基线 + 用户覆盖（用户规则优先）。
 */
import baseline from '../../config/baseline.json'
import { activeLens, prefs, ruleFor } from './prefs'
import type { Baseline, RankedItem, SearchResponse } from './types'

const B = baseline as unknown as Baseline

const RAISE_FACTOR = 3
const LOWER_FACTOR = 0.3

function positionDecay(position: number): number {
  return 1 / Math.log2(position + 2)
}

function matchDomainList(host: string, list: string[]): boolean {
  const h = host.toLowerCase().replace(/^www\./, '')
  return list.some((d) => {
    const dom = d.toLowerCase().replace(/^\./, '').replace(/^www\./, '')
    return h === dom || h.endsWith('.' + dom)
  })
}

function baselineAdjust(domain: string): number {
  if (matchDomainList(domain, B.domains.block)) return 0
  if (matchDomainList(domain, B.domains.raise)) return RAISE_FACTOR
  if (matchDomainList(domain, B.domains.lower)) return LOWER_FACTOR
  return 1
}

function normalizeUrl(raw: string): string {
  try {
    const u = new URL(raw)
    u.hash = ''
    for (const k of [...u.searchParams.keys()]) {
      const lk = k.toLowerCase()
      if (lk.startsWith('utm_') || lk === 'fbclid' || lk === 'gclid') u.searchParams.delete(k)
    }
    const host = u.host.replace(/^www\./, '')
    const path = u.pathname.replace(/\/+$/, '')
    return host + path + (u.search || '')
  } catch {
    return raw
  }
}

export function mergeAndRank(input: SearchResponse | SearchResponse[]): RankedItem[] {
  const responses = Array.isArray(input) ? input : [input]
  const map = new Map<string, RankedItem>()

  for (const resp of responses) {
    for (const eng of resp.engines) {
    if (eng.status !== 'ok') continue
    if (prefs.engines[eng.name] === false) continue // 用户显式关闭的引擎不参与
    const weight = B.engines[eng.name]?.weight ?? 1

    eng.results.forEach((r, idx) => {
      const userAction = ruleFor(r.domain)
      if (userAction === 'block') return
      let adj = baselineAdjust(r.domain)
      if (userAction === 'raise') adj = RAISE_FACTOR
      else if (userAction === 'lower') adj = LOWER_FACTOR
      if (adj === 0) return

      const score = weight * adj * positionDecay(idx)
      const key = normalizeUrl(r.url)
      const existing = map.get(key)
      if (existing) {
        existing.score = Math.max(existing.score, score)
        existing.sources.push({ engine: eng.name, position: idx + 1 })
        if (!existing.snippet && r.snippet) existing.snippet = r.snippet
      } else {
        map.set(key, {
          title: r.title,
          url: r.url,
          domain: r.domain,
          snippet: r.snippet,
          score,
          sources: [{ engine: eng.name, position: idx + 1 }],
        })
      }
    })
    }
  }

  let items = [...map.values()].sort((a, b) => b.score - a.score)

  // 类别 Lens 过滤：include 白名单 ∖ exclude 黑名单 + 关键词任一命中
  const lens = activeLens()
  if (lens) {
    items = items.filter((it) => {
      if (lens.exclude.some((d) => matchDomainList(it.domain, [d]))) return false
      if (lens.include.length && !lens.include.some((d) => matchDomainList(it.domain, [d]))) return false
      if (lens.keywords.length) {
        const hay = (it.title + ' ' + it.snippet).toLowerCase()
        if (!lens.keywords.some((k) => hay.includes(k.toLowerCase()))) return false
      }
      return true
    })
  }

  return items
}

/** 顶部外部引擎跳转（结果不可用时的兜底出口） */
export function externalLinks(query: string): { name: string; url: string }[] {
  return [
    { name: 'Google', url: `https://www.google.com/search?q=${encodeURIComponent(query)}` },
    { name: 'Bing', url: `https://www.bing.com/search?q=${encodeURIComponent(query)}` },
    { name: 'DuckDuckGo', url: `https://duckduckgo.com/?q=${encodeURIComponent(query)}` },
  ]
}

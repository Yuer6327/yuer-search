/** 前后端共享类型（后端见 search_engines/*.py 返回结构） */

export interface EngineResultItem {
  title: string
  url: string
  domain: string
  snippet: string
}

export type EngineStatus = 'ok' | 'degraded' | 'skipped' | 'error' | 'timeout'

export interface EngineResult {
  name: string
  status: EngineStatus
  latency_ms: number | null
  results: EngineResultItem[]
  note?: string
}

export interface SearchResponse {
  query: string
  lang: string
  page: number
  engines: EngineResult[]
  elapsed_ms: number
}

export type RuleAction = 'block' | 'raise' | 'lower'

/** 用户个人规则（localStorage，永不上传） */
export interface SiteRule {
  pattern: string
  action: RuleAction
  note?: string
}

/** 类别 Lens：仿 tiagozip/metasearch 的用户级类别设计 */
export interface Lens {
  id: string
  name: string
  include: string[]
  exclude: string[]
  keywords: string[]
}

export interface Prefs {
  version: 1
  rules: SiteRule[]
  lenses: Lens[]
  /** 用户引擎开关：缺省 = 跟随基线 enabled；false = 本端显式关闭 */
  engines: Record<string, boolean>
  activeLensId: string | null
}

/** config/baseline.json（前后端共用的全局基线，单一来源） */
export interface Baseline {
  version: number
  engines: Record<string, { weight: number; enabled: boolean; comment?: string }>
  domains: { block: string[]; raise: string[]; lower: string[] }
  categories: Record<string, { include: string[]; exclude: string[]; keywords: string[] }>
  pushdown?: { max_sites?: number; comment?: string }
}

/** 融合排序后的结果项 */
export interface RankedItem {
  title: string
  url: string
  domain: string
  snippet: string
  score: number
  sources: { engine: string; position: number }[]
}

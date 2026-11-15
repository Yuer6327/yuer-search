/**
 * 用户偏好层：全部存浏览器 localStorage，永不上传（0 数据收集）。
 * 设计参照 tiagozip/metasearch 的用户级规则（≤300 条域名规则）与 Lenses（≤20 类），
 * 但语义为「全局基线（config/baseline.json）之上的个人覆盖」。
 */
import { reactive, watch } from 'vue'
import type { Lens, Prefs, RuleAction, SiteRule } from './types'

const KEY = 'yuer.search.prefs.v1'
export const LIMITS = { rules: 300, lenses: 20 } as const

function emptyPrefs(): Prefs {
  return { version: 1, rules: [], lenses: [], engines: {}, activeLensId: null }
}

function load(): Prefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return emptyPrefs()
    const p = JSON.parse(raw) as Partial<Prefs>
    return {
      version: 1,
      rules: Array.isArray(p.rules) ? p.rules.slice(0, LIMITS.rules) : [],
      lenses: Array.isArray(p.lenses) ? p.lenses.slice(0, LIMITS.lenses) : [],
      engines: p.engines && typeof p.engines === 'object' ? p.engines : {},
      activeLensId: typeof p.activeLensId === 'string' ? p.activeLensId : null,
    }
  } catch {
    return emptyPrefs()
  }
}

export const prefs = reactive<Prefs>(load())

watch(
  prefs,
  (v) => {
    try {
      localStorage.setItem(KEY, JSON.stringify(v))
    } catch {
      /* 存储满/隐私模式：偏好仅在本次会话生效 */
    }
  },
  { deep: true },
)

/* ---------- 域名规则 ---------- */

export function addRule(pattern: string, action: RuleAction, note?: string): boolean {
  const p = pattern.trim().toLowerCase()
  if (!p || p.length > 200) return false
  if (prefs.rules.some((r) => r.pattern === p && r.action === action)) return true
  if (prefs.rules.length >= LIMITS.rules) return false
  prefs.rules.push({ pattern: p, action, ...(note ? { note } : {}) })
  return true
}

export function removeRule(pattern: string, action: RuleAction): void {
  const i = prefs.rules.findIndex((r) => r.pattern === pattern && r.action === action)
  if (i >= 0) prefs.rules.splice(i, 1)
}

/** 匹配单条规则模式：*.example.com 通配 / /regex/ 正则 / 纯域名后缀匹配 */
export function matchPattern(pattern: string, host: string): boolean {
  const h = host.toLowerCase()
  if (pattern.startsWith('*.')) return h.endsWith(pattern.slice(1))
  if (pattern.length > 2 && pattern.startsWith('/') && pattern.endsWith('/')) {
    try {
      return new RegExp(pattern.slice(1, -1)).test(h)
    } catch {
      return false
    }
  }
  return h === pattern || h.endsWith('.' + pattern)
}

/** 返回对某域名的用户规则动作；后添加的规则覆盖先添加的 */
export function ruleFor(host: string): RuleAction | null {
  let action: RuleAction | null = null
  for (const r of prefs.rules) {
    if (matchPattern(r.pattern, host)) action = r.action
  }
  return action
}

export function blockDomain(domain: string): boolean {
  return addRule(domain, 'block', '结果页一键屏蔽')
}

/* ---------- 类别 Lens ---------- */

let lensSeq = 0

export function addLens(name: string, include: string[] = [], exclude: string[] = [], keywords: string[] = []): Lens | null {
  if (!name.trim() || prefs.lenses.length >= LIMITS.lenses) return null
  const lens: Lens = {
    id: `lens-${Date.now()}-${lensSeq++}`,
    name: name.trim().slice(0, 40),
    include: include.map((s) => s.trim().toLowerCase()).filter(Boolean),
    exclude: exclude.map((s) => s.trim().toLowerCase()).filter(Boolean),
    keywords: keywords.map((s) => s.trim()).filter(Boolean),
  }
  prefs.lenses.push(lens)
  return lens
}

export function removeLens(id: string): void {
  const i = prefs.lenses.findIndex((l) => l.id === id)
  if (i >= 0) prefs.lenses.splice(i, 1)
  if (prefs.activeLensId === id) prefs.activeLensId = null
}

export function activeLens(): Lens | null {
  return prefs.lenses.find((l) => l.id === prefs.activeLensId) ?? null
}

/* ---------- 引擎开关 ---------- */

export function setEngine(name: string, enabled: boolean): void {
  if (enabled) delete prefs.engines[name]
  else prefs.engines[name] = false
}

export function engineEnabled(name: string): boolean {
  return prefs.engines[name] !== false
}

/* ---------- 导入 / 导出 / 重置 ---------- */

export function exportJSON(): string {
  return JSON.stringify({ ...prefs, exportedAt: new Date().toISOString() }, null, 2)
}

export function importJSON(text: string): boolean {
  try {
    const p = JSON.parse(text) as Partial<Prefs>
    if (!p || typeof p !== 'object') return false
    const next = emptyPrefs()
    if (Array.isArray(p.rules)) {
      for (const r of p.rules) {
        if (r && typeof r.pattern === 'string' && ['block', 'raise', 'lower'].includes(r.action)) {
          next.rules.push({ pattern: r.pattern, action: r.action as RuleAction })
        }
      }
      next.rules = next.rules.slice(0, LIMITS.rules)
    }
    if (Array.isArray(p.lenses)) {
      for (const l of p.lenses) {
        if (l && typeof l.name === 'string') {
          next.lenses.push({
            id: typeof l.id === 'string' ? l.id : `lens-${Date.now()}-${lensSeq++}`,
            name: l.name,
            include: Array.isArray(l.include) ? l.include.map(String) : [],
            exclude: Array.isArray(l.exclude) ? l.exclude.map(String) : [],
            keywords: Array.isArray(l.keywords) ? l.keywords.map(String) : [],
          })
        }
      }
      next.lenses = next.lenses.slice(0, LIMITS.lenses)
    }
    if (p.engines && typeof p.engines === 'object') next.engines = p.engines
    if (typeof p.activeLensId === 'string') next.activeLensId = p.activeLensId
    Object.assign(prefs, next)
    return true
  } catch {
    return false
  }
}

export function resetPrefs(): void {
  Object.assign(prefs, emptyPrefs())
}

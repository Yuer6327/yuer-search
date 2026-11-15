/**
 * Google 模式：CSE embed 控件（免费、无每日额度限制，不在 2027 JSON API 停服范围）。
 *
 * 设计要点（调研结论）：
 * - embed 是浏览器直连 Google，大陆直连用户加载不了 → 进入前先探活，不可达就优雅降级回聚合模式；
 * - 用官方 Element Control API（google.search.cse.element.render/execute）程序化渲染，
 *   配合 MutationObserver 对每次结果渲染做两件事：剥跟踪属性（Luxirty 同款思路）、
 *   按用户 localStorage 规则隐藏被屏蔽站点 + 剔除免费版广告位；
 * - cx 从 /api/config 运行时注入（Vercel 环境变量名不允许 VITE_ 前缀；cx 本身是公开值），
 *   构建期 VITE_GOOGLE_CSE_CX 仅作回退；
 * - 基线屏蔽的"源头生效"靠部署者在 CSE 控制台配置站点白名单/Annotations（见 README）；
 * - 个人"提权"在 embed 模式下只能做页面内重排、效果有限，故诚实降级为只做隐藏。
 */
import { fetchConfig } from './api'
import { ruleFor } from './prefs'
import { uiState } from './ui'

const FALLBACK_CX: string = import.meta.env.VITE_GOOGLE_CSE_CX ?? ''

const GNAME = 'yuer-results'

let probeCache: boolean | null = null
let scriptStarted = false
let configStarted = false

/** 拉取运行时配置（cx）。App 挂载时调用一次，模块级缓存 */
export async function ensureConfig(): Promise<void> {
  if (configStarted) return
  configStarted = true
  try {
    const cfg = await fetchConfig()
    uiState.googleCx = (cfg.google_cse_cx ?? '').trim()
    uiState.engineAvailability = cfg.engine_availability ?? {}
  } catch {
    /* 网络失败时回退构建期变量 */
  }
  if (!uiState.googleCx) uiState.googleCx = FALLBACK_CX.trim()
  uiState.configLoaded = true
}

/** 探活 cse.google.com：可直连 Google 的用户返回 true（被墙域名 no-cors fetch 直接 reject） */
export async function probeGoogle(timeoutMs = 2500): Promise<boolean> {
  if (probeCache !== null) return probeCache
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    await fetch('https://cse.google.com/cse.js?cx=probe', { mode: 'no-cors', signal: ctrl.signal })
    probeCache = true
  } catch {
    probeCache = false
  } finally {
    clearTimeout(timer)
  }
  return probeCache
}

function postProcess(container: HTMLElement): void {
  // 剔除 CSE 免费版的广告位（0 广告承诺；免费 embed 无法在控制台关闭广告）
  container
    .querySelectorAll('.gsc-adBlock, .gsc-adBlockHeight, .gsc-thinInlineAd, .gs-ad')
    .forEach((el) => el.remove())
  container.querySelectorAll('a').forEach((a) => {
    a.removeAttribute('data-cturl')
    a.removeAttribute('data-ctorig')
    if (a.getAttribute('target') !== '_blank') a.setAttribute('target', '_blank')
    if (!a.hasAttribute('rel')) a.setAttribute('rel', 'noopener')
  })
  container.querySelectorAll('a[href]').forEach((a) => {
    try {
      const host = new URL(a.href, location.href).hostname
      if (ruleFor(host) === 'block') {
        const block = a.closest('.gsc-result, .gs-result') ?? a.parentElement
        if (block) block.remove()
      }
    } catch {
      /* 相对地址等非法链接跳过 */
    }
  })
}

function setCallbacks(): void {
  ;(window as unknown as Record<string, unknown>).__gcse = {
    par: {},
    searchCallbacks: {
      web: { rendered: () => undefined }, // 实际后处理由 MutationObserver 兜底（见下）
    },
  }
}

function loadScript(cx: string): void {
  if (scriptStarted) return
  scriptStarted = true
  const s = document.createElement('script')
  s.src = `https://cse.google.com/cse.js?cx=${cx}`
  s.async = true
  document.head.appendChild(s)
}

/** 程序化渲染 searchresults-only 并执行初始查询；控件就绪前轮询（最多 ~8s） */
export function mountGoogleResults(container: HTMLElement, query: string): void {
  const cx = uiState.googleCx
  if (!cx) return
  setCallbacks()
  loadScript(cx)

  const observer = new MutationObserver(() => postProcess(container))
  observer.observe(container, { childList: true, subtree: true })

  const attempt = (n: number): void => {
    const gse = (window as unknown as {
      google?: { search?: { cse?: { element?: { render: (o: object) => void; getElement: (name: string) => { execute: (q: string) => void } | undefined } } } }
    }).google?.search?.cse?.element
    if (gse) {
      try {
        gse.render({
          gname: GNAME,
          div: container,
          tag: 'searchresults-only',
          attributes: { linkTarget: '_blank' },
        })
        const el = gse.getElement(GNAME)
        if (el && query) el.execute(query)
      } catch {
        container.innerHTML = '<p class="empty-state">Google 搜索控件初始化失败，请切换回聚合模式。</p>'
      }
    } else if (n < 40) {
      setTimeout(() => attempt(n + 1), 200)
    } else {
      container.innerHTML = '<p class="empty-state">Google 控件加载超时（可能无法直连 Google），请切换回聚合模式。</p>'
    }
  }
  attempt(0)
}

/** 在已挂载的控件上执行新查询（结果页 q 变化时调用） */
export function runGoogleQuery(query: string): void {
  const gse = (
    window as unknown as {
      google?: { search?: { cse?: { element?: { getElement: (name: string) => { execute: (q: string) => void } | undefined } } } }
    }
  ).google?.search?.cse?.element
  const el = gse?.getElement(GNAME)
  if (el && query) el.execute(query)
}

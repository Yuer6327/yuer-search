import type { SearchResponse } from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

export interface EngineAvailability {
  available: boolean
  reason?: string
}

export interface AppConfig {
  google_cse_cx?: string
  brave_enabled?: boolean
  engine_availability?: Record<string, EngineAvailability>
}

let configCache: AppConfig | null = null

/** 运行时配置：Vercel 环境变量名不允许 VITE_ 前缀，故 cx 由 /api/config 注入 */
export async function fetchConfig(): Promise<AppConfig> {
  if (configCache) return configCache
  try {
    const res = await fetch('/api/config')
    if (res.ok) {
      configCache = (await res.json()) as AppConfig
      return configCache
    }
  } catch {
    /* 回退到构建期变量 */
  }
  configCache = { google_cse_cx: import.meta.env.VITE_GOOGLE_CSE_CX ?? '', brave_enabled: false }
  return configCache
}

/** 按引擎子集搜索（两段式渐进加载的基础；engines 为空 = 服务端默认全部） */
export async function fetchSearchEngines(
  q: string,
  engines: string[],
  page = 1,
  fresh = false,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, page: String(page), engines: engines.join(',') })
  if (fresh) params.set('_', String(Date.now()))
  let res: Response
  try {
    res = await fetch(`/api/search?${params.toString()}`)
  } catch {
    throw new ApiError('网络请求失败：无法连接搜索服务', 0)
  }
  if (!res.ok) throw new ApiError(`搜索服务返回 ${res.status}`, res.status)
  return (await res.json()) as SearchResponse
}

export async function fetchSearch(q: string, page = 1, fresh = false): Promise<SearchResponse> {
  return fetchSearchEngines(q, [], page, fresh)
}

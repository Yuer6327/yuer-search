import type { SearchResponse } from './types'

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

/** 调用聚合搜索 API；fresh=true 时加时间戳参数绕过边缘缓存 */
export async function fetchSearch(q: string, page = 1, fresh = false): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, page: String(page) })
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

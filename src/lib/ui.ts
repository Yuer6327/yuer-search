import { reactive } from 'vue'
import type { EngineAvailability } from './api'

/** 全局 UI 状态（仅前端，不入 localStorage） */
export const uiState = reactive({
  settingsOpen: false,
  /** Google CSE cx（由 /api/config 运行时注入；cx 是公开值） */
  googleCx: '',
  /** 服务端配置门禁：缺少密钥或服务端停用的引擎由设置面板置灰 */
  engineAvailability: {} as Record<string, EngineAvailability>,
  configLoaded: false,
})

export function openSettings(): void {
  uiState.settingsOpen = true
}

export function closeSettings(): void {
  uiState.settingsOpen = false
}

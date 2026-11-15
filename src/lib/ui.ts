import { reactive } from 'vue'

/** 全局 UI 状态（仅前端，不入 localStorage） */
export const uiState = reactive({
  settingsOpen: false,
  /** Google CSE cx（由 /api/config 运行时注入；cx 是公开值） */
  googleCx: '',
  configLoaded: false,
})

export function openSettings(): void {
  uiState.settingsOpen = true
}

export function closeSettings(): void {
  uiState.settingsOpen = false
}

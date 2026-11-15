/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Google CSE cx（可选；不配置则隐藏 Google 模式） */
  readonly VITE_GOOGLE_CSE_CX?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

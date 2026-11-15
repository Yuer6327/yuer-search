<script setup lang="ts">
import type { EngineResult } from '@/lib/types'

defineProps<{ engines: EngineResult[] }>()

const LABELS: Record<string, string> = {
  bing: 'Bing',
  google: 'Google',
  ddg: 'DuckDuckGo',
  mojeek: 'Mojeek',
  bilibili: 'B 站',
  baidu: '百度',
  marginalia: 'Marginalia',
  brave: 'Brave',
  tavily: 'Tavily',
  serper: 'Serper',
  brightdata: 'BrightData',
  exa: 'Exa',
  firecrawl: 'Firecrawl',
  scraperapi: 'ScraperAPI',
  hasdata: 'HasData',
  searxng: 'SearXNG',
}
const STATUS_LABEL: Record<string, string> = {
  ok: '',
  degraded: '降级',
  skipped: '跳过',
  error: '失败',
  timeout: '超时',
}
</script>

<template>
  <div class="engine-chips" role="status">
    <span
      v-for="e in engines"
      :key="e.name"
      class="chip"
      :class="e.status"
      :title="e.note || e.status"
    >
      <span class="dot" aria-hidden="true" />
      {{ LABELS[e.name] ?? e.name }}
      <template v-if="e.status === 'ok' && e.latency_ms != null">
        {{ e.results.length }} 条
      </template>
      <template v-else-if="e.status !== 'ok'">
        {{ STATUS_LABEL[e.status] }}
      </template>
    </span>
  </div>
</template>

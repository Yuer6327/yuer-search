<script setup lang="ts">
import type { EngineResult } from '@/lib/types'

defineProps<{ engines: EngineResult[] }>()

const LABELS: Record<string, string> = {
  google: 'Google(CSE)',
  ddg: 'DuckDuckGo',
  bing: 'Bing',
  marginalia: 'Marginalia',
  brave: 'Brave',
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
      <span class="dot" />
      {{ LABELS[e.name] ?? e.name }}
      <template v-if="e.status === 'ok' && e.latency_ms != null">
        · {{ e.latency_ms }}ms · {{ e.results.length }} 条
      </template>
      <template v-else-if="e.status !== 'ok'">
        · {{ STATUS_LABEL[e.status] }}<template v-if="e.note">：{{ e.note }}</template>
      </template>
    </span>
  </div>
</template>

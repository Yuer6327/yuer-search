<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EngineChips from '@/components/EngineChips.vue'
import ResultItem from '@/components/ResultItem.vue'
import SearchBar from '@/components/SearchBar.vue'
import { ApiError, fetchSearchEngines } from '@/lib/api'
import { ensureConfig, mountGoogleResults, probeGoogle, runGoogleQuery } from '@/lib/googleMode'
import { externalLinks, mergeAndRank, engineOn } from '@/lib/rank'
import { openSettings, uiState } from '@/lib/ui'
import type { SearchResponse } from '@/lib/types'

const route = useRoute()
const router = useRouter()

const q = computed(() => String(route.query.q ?? '').trim())
const mode = computed<'agg' | 'google'>(() => (route.query.mode === 'google' ? 'google' : 'agg'))

/**
 * 两段式渐进加载：
 * 第一段 = 第一个启用引擎（默认 Bing，中文主力）→ 响应一到立即筛选排序渲染；
 * 第二段 = 其余引擎并行后台抓 → 完成后出「点击重排」提示，点击仅做前端合并排序，
 *          不发送任何新请求。两段共用同一次上游抓取（engines 参数分片），边缘缓存各自独立。
 */
const respFast = ref<SearchResponse | null>(null)
const respRest = ref<SearchResponse | null>(null)
const restPending = ref(false)
const restError = ref('')
const visible = ref<'fast' | 'all'>('fast')
const showRerankHint = ref(false)
const loading = ref(false)
const error = ref('')
const page = ref(1)
const googleOk = ref<boolean | null>(null)
const googleContainer = ref<HTMLElement | null>(null)

let seq = 0

const ENGINE_ORDER = [
  'bing',
  'google',
  'ddg',
  'mojeek',
  'bilibili',
  'baidu',
  'marginalia',
  'brave',
  'tavily',
  'serper',
  'brightdata',
  'exa',
  'firecrawl',
  'scraperapi',
  'hasdata',
  'searxng',
]

function splitEngines(): { fast: string[]; rest: string[] } {
  const enabled = ENGINE_ORDER.filter((name) => engineOn(name))
  if (!enabled.length) return { fast: ['bing'], rest: [] }
  return { fast: [enabled[0]], rest: enabled.slice(1) }
}

const visibleSources = computed<SearchResponse[]>(() => {
  const arr: SearchResponse[] = []
  if (respFast.value) arr.push(respFast.value)
  if (visible.value === 'all' && respRest.value) arr.push(respRest.value)
  return arr
})
const items = computed(() => mergeAndRank(visibleSources.value))
const hasMore = computed(() =>
  visibleSources.value.some((r) => r.engines.some((e) => e.status === 'ok' && e.results.length >= 10)),
)

async function search(fresh = false): Promise<void> {
  if (!q.value || mode.value !== 'agg') return
  const mySeq = ++seq
  const { fast, rest } = splitEngines()
  loading.value = true
  error.value = ''
  respFast.value = null
  respRest.value = null
  restPending.value = false
  restError.value = ''
  visible.value = 'fast'
  showRerankHint.value = false

  const p1 = fetchSearchEngines(q.value, fast, page.value, fresh).then(
    (r) => {
      if (mySeq === seq) respFast.value = r
    },
    (e: unknown) => {
      if (mySeq === seq) error.value = e instanceof ApiError ? e.message : String(e)
    },
  )
  const p2 = rest.length
    ? fetchSearchEngines(q.value, rest, page.value, fresh).then(
        (r) => {
          if (mySeq === seq) respRest.value = r
        },
        (e: unknown) => {
          if (mySeq === seq) restError.value = e instanceof ApiError ? e.message : String(e)
        },
      )
    : null

  await p1 // 第一批结果一到就渲染，不等其余引擎
  if (mySeq !== seq) return
  loading.value = false

  if (!p2) return
  restPending.value = true
  await p2
  if (mySeq !== seq) return
  restPending.value = false
  if (!respRest.value) return
  const added = respRest.value.engines.some((e) => e.status === 'ok' && e.results.length > 0)
  if (added && items.value.length > 0) {
    showRerankHint.value = true // 不打断阅读，等用户点击重排（纯前端合并）
  } else if (added) {
    visible.value = 'all' // 第一批为空 → 直接自动合并
  }
}

function applyRest(): void {
  visible.value = 'all'
  showRerankHint.value = false
}

function setMode(m: 'agg' | 'google'): void {
  router.push({ query: { ...route.query, mode: m } })
}

async function ensureGoogle(): Promise<void> {
  await ensureConfig()
  if (!uiState.googleCx) {
    googleOk.value = false
    return
  }
  googleOk.value = null
  googleOk.value = await probeGoogle()
  if (googleOk.value) {
    await nextTick()
    if (googleContainer.value) mountGoogleResults(googleContainer.value, q.value)
  }
}

watch(
  [q, page],
  () => {
    if (mode.value === 'agg') void search()
  },
  { immediate: true },
)

watch(mode, (m) => {
  page.value = 1
  if (m === 'google') void ensureGoogle()
  else void search()
})

watch(q, (query) => {
  if (mode.value === 'google' && googleOk.value && query) runGoogleQuery(query)
})

onMounted(() => {
  if (mode.value === 'google') void ensureGoogle()
})

function refresh(fresh = false): void {
  void search(fresh)
}
</script>

<template>
  <div>
    <header class="topbar">
      <router-link to="/" class="mini-logo">Yuer</router-link>
      <SearchBar :initial="q" />
      <div class="mode-switch">
        <button :class="{ on: mode === 'agg' }" @click="setMode('agg')">聚合</button>
        <button v-if="uiState.googleCx" :class="{ on: mode === 'google' }" @click="setMode('google')">
          Google
        </button>
      </div>
      <button class="icon-btn" title="设置（每用户权重 / 类别 / 引擎开关）" @click="openSettings">⚙</button>
    </header>

    <!-- Google 模式 -->
    <main v-if="mode === 'google'" class="results">
      <div v-if="!uiState.googleCx" class="empty-state">
        未配置 Google 模式：Vercel 环境变量 GOOGLE_CSE_CX 未设置（见 README）。
      </div>
      <div v-else-if="googleOk === false" class="empty-state">
        <p>当前网络无法直连 Google，Google 模式不可用。</p>
        <button class="btn primary" @click="setMode('agg')">切换到聚合模式</button>
      </div>
      <div v-else-if="googleOk" ref="googleContainer" class="google-container" />
      <div v-else class="empty-state">正在检测 Google 可达性…</div>
    </main>

    <!-- 聚合模式 -->
    <main v-else class="results">
      <EngineChips v-if="respFast" :engines="respFast.engines" />
      <EngineChips v-if="respRest && visible === 'all'" :engines="respRest.engines" />
      <span v-if="restPending" class="chip"><span class="dot" />其余引擎 · 抓取中…</span>
      <span v-else-if="restError" class="chip error"><span class="dot" />其余引擎 · {{ restError }}</span>
      <div v-if="respFast" class="engine-chips">
        <button class="chip" title="绕过边缘缓存重新聚合" @click="refresh(true)">↻ 强制刷新</button>
      </div>

      <div v-if="showRerankHint" class="rerank-hint">
        <span>已获取到更多引擎的结果</span>
        <button class="btn primary" @click="applyRest">点击重排</button>
      </div>

      <template v-if="loading">
        <div v-for="i in 6" :key="i" class="skeleton">
          <div class="bar" style="width: 58%" />
          <div class="bar" style="width: 92%; margin-top: 9px" />
          <div class="bar" style="width: 74%; margin-top: 8px; height: 11px" />
        </div>
      </template>

      <div v-else-if="error" class="empty-state">
        <p>{{ error }}</p>
        <button class="btn" @click="refresh()">重试</button>
        <div class="fallback-links">
          <a v-for="l in externalLinks(q)" :key="l.name" :href="l.url" target="_blank" rel="noopener">{{ l.name }}</a>
        </div>
      </div>

      <template v-else>
        <div v-if="!items.length && !restPending" class="empty-state">
          <p>没有可显示的结果。</p>
          <p class="hint" style="font-size: 13px">
            所有引擎都失败或结果被过滤。可点「强制刷新」重试，或切换引擎设置。
          </p>
        </div>
        <ResultItem v-for="it in items" :key="it.url" :item="it" />

        <div class="pager">
          <button class="btn" :disabled="page <= 1" @click="page--">上一页</button>
          <span>第 {{ page }} 页</span>
          <button class="btn" :disabled="loading || !hasMore" @click="page++">下一页</button>
        </div>

        <div class="fallback-links">
          <span>其他引擎：</span>
          <a v-for="l in externalLinks(q)" :key="l.name" :href="l.url" target="_blank" rel="noopener">{{ l.name }}</a>
        </div>
      </template>
    </main>
  </div>
</template>

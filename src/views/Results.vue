<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { PhArrowDown, PhArrowLeft, PhArrowRight, PhArrowClockwise, PhSlidersHorizontal } from '@phosphor-icons/vue'
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
  const enabled = ENGINE_ORDER.filter(
    (name) => engineOn(name) && uiState.engineAvailability[name]?.available === true,
  )
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
  loading.value = true
  error.value = ''
  respFast.value = null
  respRest.value = null
  restPending.value = false
  restError.value = ''
  visible.value = 'fast'
  showRerankHint.value = false

  // 先拿到服务端配置，避免把缺密钥的引擎排进请求
  await ensureConfig()
  if (mySeq !== seq) return
  const { fast, rest } = splitEngines()

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
  <div class="search-page">
    <header class="topbar">
      <router-link to="/" class="mini-logo" aria-label="Yuer Search 首页">Yuer Search<span>.</span></router-link>
      <SearchBar :initial="q" />
      <div class="topbar-actions">
        <div class="mode-switch" aria-label="搜索模式">
          <button :class="{ on: mode === 'agg' }" :aria-pressed="mode === 'agg'" @click="setMode('agg')">聚合</button>
          <button v-if="uiState.googleCx" :class="{ on: mode === 'google' }" :aria-pressed="mode === 'google'" @click="setMode('google')">
            Google
          </button>
        </div>
        <button class="icon-btn" title="偏好设置" aria-label="打开偏好设置" @click="openSettings">
          <PhSlidersHorizontal :size="20" weight="light" aria-hidden="true" />
        </button>
      </div>
    </header>

    <!-- Google 模式 -->
    <main v-if="mode === 'google'" class="results">
      <div v-if="!uiState.googleCx" class="empty-state">
        <h1>Google 模式未配置</h1>
        <p>请设置 Vercel 环境变量 GOOGLE_CSE_CX，或返回聚合模式。</p>
        <button class="btn primary" @click="setMode('agg')">返回聚合模式</button>
      </div>
      <div v-else-if="googleOk === false" class="empty-state">
        <h1>当前网络无法连接 Google</h1>
        <p>你仍可以使用多引擎聚合搜索。</p>
        <button class="btn primary" @click="setMode('agg')">切换到聚合模式</button>
      </div>
      <div v-else-if="googleOk" ref="googleContainer" class="google-container" />
      <div v-else class="empty-state">正在连接 Google…</div>
    </main>

    <!-- 聚合模式 -->
    <main v-else class="results">
      <div class="results-heading">
        <h1>搜索结果<span v-if="q" class="result-query">“{{ q }}”</span></h1>
        <button v-if="respFast" class="refresh-btn" title="绕过缓存，重新搜索" @click="refresh(true)">
          <PhArrowClockwise :size="16" weight="light" aria-hidden="true" />
          刷新
        </button>
      </div>

      <div v-if="respFast || restPending || restError" class="engine-status">
        <EngineChips v-if="respFast" :engines="respFast.engines" />
        <EngineChips v-if="respRest && visible === 'all'" :engines="respRest.engines" />
        <span v-if="restPending" class="status-note">正在查找更多结果…</span>
        <span v-else-if="restError" class="status-note">其他引擎暂时不可用</span>
      </div>

      <div v-if="showRerankHint" class="rerank-hint" role="status">
        <span>更多结果已就绪</span>
        <button class="text-action" @click="applyRest">合并并重排 <PhArrowDown :size="16" weight="light" aria-hidden="true" /></button>
      </div>

      <template v-if="loading">
        <div class="loading-label" role="status">正在搜索</div>
        <div v-for="i in 5" :key="i" class="skeleton" aria-hidden="true">
          <div class="bar domain-bar" />
          <div class="bar title-bar" />
          <div class="bar snippet-bar" />
          <div class="bar snippet-bar short" />
        </div>
      </template>

      <div v-else-if="error" class="empty-state">
        <h2>这次搜索没有完成</h2>
        <p>{{ error }}</p>
        <button class="btn primary" @click="refresh()">重新搜索</button>
        <div class="fallback-links">
          <span>也可以尝试</span>
          <a v-for="l in externalLinks(q)" :key="l.name" :href="l.url" target="_blank" rel="noopener">{{ l.name }}</a>
        </div>
      </div>

      <template v-else>
        <div v-if="!items.length && !restPending" class="empty-state">
          <h2>没有找到相关结果</h2>
          <p>试试更简短的关键词，或在偏好设置中检查站点过滤规则。</p>
          <button class="btn primary" @click="refresh(true)">重新搜索</button>
        </div>
        <section v-else class="result-list" aria-label="搜索结果">
          <ResultItem v-for="it in items" :key="it.url" :item="it" @changed="refresh()" />
        </section>

        <nav v-if="items.length" class="pager" aria-label="搜索结果分页">
          <button class="page-btn" :disabled="page <= 1" @click="page--">
            <PhArrowLeft :size="17" weight="light" aria-hidden="true" />
            上一页
          </button>
          <span>{{ String(page).padStart(2, '0') }}</span>
          <button class="page-btn" :disabled="loading || !hasMore" @click="page++">
            下一页
            <PhArrowRight :size="17" weight="light" aria-hidden="true" />
          </button>
        </nav>

        <div v-if="items.length" class="fallback-links">
          <span>继续搜索</span>
          <a v-for="l in externalLinks(q)" :key="l.name" :href="l.url" target="_blank" rel="noopener">{{ l.name }}</a>
        </div>
      </template>
    </main>
  </div>
</template>

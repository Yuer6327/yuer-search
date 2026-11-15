<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EngineChips from '@/components/EngineChips.vue'
import ResultItem from '@/components/ResultItem.vue'
import SearchBar from '@/components/SearchBar.vue'
import { ApiError, fetchSearch } from '@/lib/api'
import { CSE_CX, mountGoogleResults, probeGoogle, runGoogleQuery } from '@/lib/googleMode'
import { externalLinks, mergeAndRank } from '@/lib/rank'
import { openSettings } from '@/lib/ui'
import type { SearchResponse } from '@/lib/types'

const route = useRoute()
const router = useRouter()

const q = computed(() => String(route.query.q ?? '').trim())
const mode = computed<'agg' | 'google'>(() => (route.query.mode === 'google' ? 'google' : 'agg'))

const resp = ref<SearchResponse | null>(null)
const loading = ref(false)
const error = ref('')
const page = ref(1)
const googleOk = ref<boolean | null>(null)
const googleContainer = ref<HTMLElement | null>(null)

const items = computed(() => (resp.value ? mergeAndRank(resp.value) : []))
const hasMore = computed(() =>
  (resp.value?.engines ?? []).some((e) => e.status === 'ok' && e.results.length >= 10),
)

async function load(fresh = false): Promise<void> {
  if (!q.value) return
  loading.value = true
  error.value = ''
  try {
    resp.value = await fetchSearch(q.value, page.value, fresh)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e)
    resp.value = null
  } finally {
    loading.value = false
  }
}

function setMode(m: 'agg' | 'google'): void {
  router.push({ query: { ...route.query, mode: m } })
}

async function ensureGoogle(): Promise<void> {
  if (!CSE_CX) {
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
    if (mode.value === 'agg') void load()
  },
  { immediate: true },
)

watch(mode, (m) => {
  page.value = 1
  if (m === 'google') void ensureGoogle()
  else void load()
})

watch(q, (query) => {
  if (mode.value === 'google' && googleOk.value && query) runGoogleQuery(query)
})

onMounted(() => {
  if (mode.value === 'google') void ensureGoogle()
})

function refresh(fresh = false): void {
  void load(fresh)
}
</script>

<template>
  <div>
    <header class="topbar">
      <router-link to="/" class="mini-logo">Yuer</router-link>
      <SearchBar :initial="q" />
      <div class="mode-switch">
        <button :class="{ on: mode === 'agg' }" @click="setMode('agg')">聚合</button>
        <button v-if="CSE_CX" :class="{ on: mode === 'google' }" @click="setMode('google')">Google</button>
      </div>
      <button class="icon-btn" title="设置（每用户权重 / 类别 / 引擎开关）" @click="openSettings">⚙</button>
    </header>

    <!-- Google 模式 -->
    <main v-if="mode === 'google'" class="results">
      <div v-if="!CSE_CX" class="empty-state">
        未配置 Google 模式：部署时需设置环境变量 VITE_GOOGLE_CSE_CX（见 README）。
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
      <EngineChips v-if="resp" :engines="resp.engines" />
      <div v-if="resp" class="engine-chips">
        <button class="chip" title="绕过边缘缓存重新聚合" @click="refresh(true)">↻ 强制刷新</button>
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
        <div v-if="!items.length" class="empty-state">
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

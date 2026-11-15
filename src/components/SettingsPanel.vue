<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { PhX } from '@phosphor-icons/vue'
import baseline from '../../config/baseline.json'
import { closeSettings, uiState } from '@/lib/ui'
import {
  LIMITS,
  addLens,
  addRule,
  engineEnabled,
  exportJSON,
  importJSON,
  prefs,
  removeLens,
  removeRule,
  resetPrefs,
  setEngine,
} from '@/lib/prefs'
import type { EngineAvailability } from '@/lib/api'
import type { Baseline, RuleAction } from '@/lib/types'

const B = baseline as unknown as Baseline
const ENGINE_LABELS: Record<string, string> = {
  bing: 'Bing',
  google: 'Google',
  ddg: 'DuckDuckGo',
  mojeek: 'Mojeek',
  bilibili: 'B 站',
  zhihu: '知乎',
  baidu: '百度',
  marginalia: 'Marginalia',
  brave: 'Brave（可选）',
  tavily: 'Tavily',
  serper: 'Serper',
  brightdata: 'BrightData',
  exa: 'Exa',
  firecrawl: 'Firecrawl',
  scraperapi: 'ScraperAPI',
  hasdata: 'HasData',
  searxng: 'SearXNG',
}

const panel = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null

const newPattern = ref('')
const newAction = ref<RuleAction>('block')
const lensName = ref('')
const lensInclude = ref('')
const lensExclude = ref('')
const lensKeywords = ref('')
const importMsg = ref('')

function engineState(name: string): EngineAvailability {
  if (!uiState.configLoaded) return { available: false, reason: '正在检测配置' }
  return uiState.engineAvailability[name] ?? { available: false, reason: '配置不可用' }
}

function onEngineToggle(name: string, enabled: boolean): void {
  if (engineState(name).available) setEngine(name, enabled)
}

/** 可用引擎保持基线顺序，未配置/停用的引擎自动沉底（组内仍保持原顺序）。 */
const engineNames = computed(() =>
  Object.keys(B.engines).sort((a, b) => Number(engineState(b).available) - Number(engineState(a).available)),
)

watch(
  () => uiState.settingsOpen,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement as HTMLElement | null
      document.body.style.overflow = 'hidden'
      await nextTick()
      closeButton.value?.focus()
    } else {
      document.body.style.overflow = ''
      previousFocus?.focus()
    }
  },
)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
})

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    closeSettings()
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const focusable = Array.from(
    panel.value.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select, textarea, label[tabindex]'),
  )
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

function onAddRule(): void {
  if (addRule(newPattern.value, newAction.value)) {
    newPattern.value = ''
    importMsg.value = ''
  } else {
    importMsg.value = '添加失败：模式为空或已达上限'
  }
}

function onCreateLens(): void {
  const lens = addLens(
    lensName.value,
    lensInclude.value.split(/[\n,，]+/),
    lensExclude.value.split(/[\n,，]+/),
    lensKeywords.value.split(/[\n,，]+/),
  )
  if (lens) {
    prefs.activeLensId = lens.id
    lensName.value = lensInclude.value = lensExclude.value = lensKeywords.value = ''
    importMsg.value = ''
  } else {
    importMsg.value = '创建失败：名称为空或已达上限'
  }
}

function onExport(): void {
  const blob = new Blob([exportJSON()], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = 'yuer-search-prefs.json'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function onImportFile(ev: Event): Promise<void> {
  const file = (ev.target as HTMLInputElement).files?.[0]
  if (!file) return
  const ok = importJSON(await file.text())
  importMsg.value = ok ? '导入成功' : '导入失败：文件格式不正确'
  if (ok) (ev.target as HTMLInputElement).value = ''
}

function onReset(): void {
  if (confirm('确定恢复默认？所有个人规则与类别将被清空。')) {
    resetPrefs()
    importMsg.value = ''
  }
}
</script>

<template>
  <Teleport to="body">
    <template v-if="uiState.settingsOpen">
      <div class="overlay" @click="closeSettings" />
      <aside ref="panel" class="panel" role="dialog" aria-modal="true" aria-labelledby="settings-title" @keydown="onKeydown">
        <div class="panel-head">
          <h1 id="settings-title">偏好设置</h1>
          <button ref="closeButton" class="icon-btn" title="关闭设置" aria-label="关闭设置" @click="closeSettings">
            <PhX :size="21" weight="light" aria-hidden="true" />
          </button>
        </div>
        <div class="panel-body">
          <h2>搜索引擎</h2>
          <div
            v-for="name in engineNames"
            :key="name"
            class="switch-row"
            :class="{ unavailable: !engineState(name).available }"
          >
            <label :for="`engine-${name}`" :title="engineState(name).reason || undefined">
              {{ ENGINE_LABELS[name] ?? name }}
              <span v-if="engineState(name).available" class="hint">权重 ×{{ B.engines[name]?.weight ?? 1 }}</span>
              <span v-else class="hint">{{ engineState(name).reason }}</span>
            </label>
            <input
              :id="`engine-${name}`"
              type="checkbox"
              :checked="engineState(name).available && engineEnabled(name)"
              :disabled="!engineState(name).available"
              @change="onEngineToggle(name, ($event.target as HTMLInputElement).checked)"
            />
          </div>
          <p class="hint">灰色项缺少服务端配置或已停用，当前无法启用。开关仅保存在本浏览器。</p>

          <h2>站点规则（{{ prefs.rules.length }}/{{ LIMITS.rules }}）</h2>
          <p class="hint">匹配域名及其子域名。支持通配符与正则表达式，后添加的规则优先。</p>
          <div v-for="r in prefs.rules" :key="r.pattern + r.action" class="rule-row">
            <span class="action-tag" :class="r.action">{{
              r.action === 'block' ? '屏蔽' : r.action === 'raise' ? '提权' : '降权'
            }}</span>
            <span>{{ r.pattern }}</span>
            <button class="row-delete" :title="`删除规则 ${r.pattern}`" :aria-label="`删除规则 ${r.pattern}`" @click="removeRule(r.pattern, r.action)">
              <PhX :size="15" weight="light" aria-hidden="true" />
            </button>
          </div>
          <form class="add-form" @submit.prevent="onAddRule">
            <label class="sr-only" for="rule-pattern">域名匹配规则</label>
            <input id="rule-pattern" v-model="newPattern" placeholder="例如 csdn.net 或 *.spam.example" />
            <label class="sr-only" for="rule-action">规则操作</label>
            <select id="rule-action" v-model="newAction">
              <option value="block">屏蔽</option>
              <option value="raise">提权</option>
              <option value="lower">降权</option>
            </select>
            <button class="btn primary" type="submit" :disabled="!newPattern.trim()">添加规则</button>
          </form>

          <h2>搜索类别（{{ prefs.lenses.length }}/{{ LIMITS.lenses }}）</h2>
          <div class="switch-row">
            <label for="active-lens">当前生效</label>
            <select id="active-lens" v-model="prefs.activeLensId">
              <option :value="null">全部结果</option>
              <option v-for="l in prefs.lenses" :key="l.id" :value="l.id">{{ l.name }}</option>
            </select>
          </div>
          <div v-for="l in prefs.lenses" :key="l.id" class="lens-row">
            <span>
              <strong>{{ l.name }}</strong>
              <span class="hint">包含 {{ l.include.length }} 站点，排除 {{ l.exclude.length }} 站点</span>
            </span>
            <button class="row-delete" :title="`删除类别 ${l.name}`" :aria-label="`删除类别 ${l.name}`" @click="removeLens(l.id)">
              <PhX :size="15" weight="light" aria-hidden="true" />
            </button>
          </div>
          <form class="add-form form-stack" @submit.prevent="onCreateLens">
            <div>
              <label class="field-label" for="lens-name">类别名称</label>
              <input id="lens-name" v-model="lensName" placeholder="例如：开发" />
            </div>
            <div>
              <label class="field-label" for="lens-include">仅显示这些域名，每行一个</label>
              <textarea id="lens-include" v-model="lensInclude" placeholder="留空则不限制" />
            </div>
            <div>
              <label class="field-label" for="lens-exclude">排除这些域名，每行一个</label>
              <textarea id="lens-exclude" v-model="lensExclude" placeholder="留空则不排除" />
            </div>
            <div>
              <label class="field-label" for="lens-keywords">保留任一关键词命中的结果</label>
              <input id="lens-keywords" v-model="lensKeywords" placeholder="用逗号分隔，留空则不限制" />
            </div>
            <button class="btn primary" type="submit" :disabled="!lensName.trim()">创建类别</button>
          </form>

          <h2>你的数据</h2>
          <div class="add-form">
            <button class="btn" @click="onExport">导出</button>
            <label class="btn" tabindex="0" @keydown.enter.prevent="($event.target as HTMLElement).click()" @keydown.space.prevent="($event.target as HTMLElement).click()">
              导入<input type="file" accept="application/json" class="sr-only" @change="onImportFile" />
            </label>
            <button class="btn danger" @click="onReset">恢复默认</button>
          </div>
          <p v-if="importMsg" class="hint" role="status">{{ importMsg }}</p>

          <h2>隐私</h2>
          <p class="hint">
            所有偏好仅保存在本浏览器，不上传。服务端不记录查询，不设置 Cookie，不做统计。
            搜索关键词会发送给所选的上游引擎。
          </p>
        </div>
      </aside>
    </template>
  </Teleport>
</template>

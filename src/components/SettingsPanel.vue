<script setup lang="ts">
import { ref } from 'vue'
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
import type { Baseline, RuleAction } from '@/lib/types'

const B = baseline as unknown as Baseline
const engineNames = Object.keys(B.engines)
const ENGINE_LABELS: Record<string, string> = {
  bing: 'Bing',
  google: 'Google(CSE)',
  ddg: 'DuckDuckGo',
  mojeek: 'Mojeek',
  bilibili: 'B 站',
  baidu: '百度',
  marginalia: 'Marginalia',
  brave: 'Brave（可选）',
  tavily: 'Tavily',
  serper: 'Serper(Google)',
  brightdata: 'BrightData(百度)',
  exa: 'Exa',
  firecrawl: 'Firecrawl',
  scraperapi: 'ScraperAPI(百度)',
  hasdata: 'HasData(百度)',
  searxng: 'SearXNG',
}

const newPattern = ref('')
const newAction = ref<RuleAction>('block')
const lensName = ref('')
const lensInclude = ref('')
const lensExclude = ref('')
const lensKeywords = ref('')
const importMsg = ref('')

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
      <aside class="panel" role="dialog" aria-label="设置">
        <div class="panel-head">
          <span>设置</span>
          <button class="icon-btn" @click="closeSettings">✕</button>
        </div>
        <div class="panel-body">
          <h3>引擎开关</h3>
          <div v-for="name in engineNames" :key="name" class="switch-row">
            <span>
              {{ ENGINE_LABELS[name] ?? name }}
              <span class="hint">权重 ×{{ B.engines[name]?.weight ?? 1 }}</span>
            </span>
            <input
              type="checkbox"
              :checked="engineEnabled(name)"
              @change="setEngine(name, ($event.target as HTMLInputElement).checked)"
            />
          </div>
          <p class="hint">关闭引擎只影响本浏览器；Brave 还需服务端设 BRAVE_ENABLED=1。</p>

          <h3>站点规则（{{ prefs.rules.length }}/{{ LIMITS.rules }}）</h3>
          <p class="hint">匹配域名及其子域名；支持 *.example.com 通配与 /正则/；后添加的覆盖先添加的。</p>
          <div v-for="r in prefs.rules" :key="r.pattern + r.action" class="rule-row">
            <span class="action-tag" :class="r.action">{{
              r.action === 'block' ? '屏蔽' : r.action === 'raise' ? '提权' : '降权'
            }}</span>
            <span>{{ r.pattern }}</span>
            <button class="row-delete" title="删除" @click="removeRule(r.pattern, r.action)">✕</button>
          </div>
          <div class="add-form">
            <input v-model="newPattern" placeholder="如 csdn.net 或 *.spam.example" />
            <select v-model="newAction">
              <option value="block">屏蔽</option>
              <option value="raise">提权</option>
              <option value="lower">降权</option>
            </select>
            <button class="btn primary" @click="onAddRule">添加</button>
          </div>

          <h3>类别 Lens（{{ prefs.lenses.length }}/{{ LIMITS.lenses }}）</h3>
          <div class="switch-row">
            <span>当前生效</span>
            <select v-model="prefs.activeLensId">
              <option :value="null">无（全部结果）</option>
              <option v-for="l in prefs.lenses" :key="l.id" :value="l.id">{{ l.name }}</option>
            </select>
          </div>
          <div v-for="l in prefs.lenses" :key="l.id" class="lens-row">
            <span>
              <strong>{{ l.name }}</strong>
              <span class="hint"> 含 {{ l.include.length }} 站点 · 排除 {{ l.exclude.length }} · 关键词 {{ l.keywords.length }} </span>
            </span>
            <button class="row-delete" title="删除" @click="removeLens(l.id)">✕</button>
          </div>
          <div class="add-form" style="flex-direction: column">
            <input v-model="lensName" placeholder="类别名称，如：开发" />
            <textarea v-model="lensInclude" placeholder="仅显示这些域名（每行一个，留空 = 不限）" />
            <textarea v-model="lensExclude" placeholder="排除这些域名（每行一个）" />
            <input v-model="lensKeywords" placeholder="关键词（逗号分隔，任一命中即保留，留空 = 不限）" />
            <button class="btn primary" @click="onCreateLens">创建类别</button>
          </div>

          <h3>数据</h3>
          <div class="add-form">
            <button class="btn" @click="onExport">导出 JSON</button>
            <label class="btn" style="display: inline-flex">
              导入 JSON<input type="file" accept="application/json" style="display: none" @change="onImportFile" />
            </label>
            <button class="btn danger" @click="onReset">恢复默认</button>
          </div>
          <p v-if="importMsg" class="hint">{{ importMsg }}</p>

          <h3>隐私</h3>
          <p class="hint">
            所有偏好仅保存在本浏览器 localStorage，永不上传；服务端不记录查询、不设 Cookie、无统计。
            搜索查询本身会发往上游引擎（任何搜索引擎皆然），详见页面底部隐私说明。
          </p>
        </div>
      </aside>
    </template>
  </Teleport>
</template>

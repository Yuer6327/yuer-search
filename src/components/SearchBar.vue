<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { PhArrowUp, PhMagnifyingGlass, PhX } from '@phosphor-icons/vue'
import { useRoute, useRouter } from 'vue-router'

const props = defineProps<{ initial?: string; large?: boolean }>()
const router = useRouter()
const route = useRoute()
const q = ref(props.initial ?? '')
const input = ref<HTMLInputElement | null>(null)

watch(
  () => props.initial,
  (v) => {
    q.value = v ?? ''
  },
)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey) {
    const target = event.target as HTMLElement | null
    if (target?.matches('input, textarea, select, [contenteditable="true"]')) return
    event.preventDefault()
    input.value?.focus()
  }
  if (event.key === 'Escape' && route.name === 'search') {
    input.value?.blur()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})

function submit(): void {
  const query = q.value.trim()
  if (!query) return
  const mode = router.currentRoute.value.query.mode ?? 'agg'
  void router.push({ path: '/search', query: { q: query, mode } })
}

function clear(): void {
  q.value = ''
  void nextTick(() => input.value?.focus())
}

defineExpose({ focus: () => input.value?.focus() })
</script>

<template>
  <div>
    <form class="searchbox" :class="{ large }" role="search" @submit.prevent="submit" @keydown="onKeydown">
      <PhMagnifyingGlass class="search-icon" :size="large ? 24 : 20" weight="light" aria-hidden="true" />
      <label class="sr-only" for="search-input">搜索关键词</label>
      <input
        id="search-input"
        ref="input"
        v-model="q"
        type="search"
        placeholder="搜索任何内容"
        aria-label="搜索关键词"
        enterkeyhint="search"
        autocomplete="off"
        spellcheck="false"
        autofocus
      />
      <button v-if="q" class="clear-btn" type="button" title="清空搜索" aria-label="清空搜索" @click="clear">
        <PhX :size="18" weight="light" aria-hidden="true" />
      </button>
      <button class="go" type="submit" :disabled="!q.trim()" title="搜索" aria-label="搜索">
        <PhArrowUp :size="large ? 22 : 20" weight="light" aria-hidden="true" />
        <span class="sr-only">搜索</span>
      </button>
    </form>
  </div>
</template>

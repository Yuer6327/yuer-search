<script setup lang="ts">
import { computed } from 'vue'
import { blockDomain } from '@/lib/prefs'
import type { RankedItem } from '@/lib/types'

const props = defineProps<{ item: RankedItem }>()
const emit = defineEmits<{ changed: [] }>()

const displayUrl = computed(() => {
  try {
    const u = new URL(props.item.url)
    return u.host.replace(/^www\./, '') + u.pathname + u.search
  } catch {
    return props.item.url
  }
})

function block(): void {
  if (blockDomain(props.item.domain)) emit('changed')
}
</script>

<template>
  <article class="result-item">
    <div class="title-line">
      <a class="title" :href="item.url" target="_blank" rel="noopener">{{ item.title }}</a>
    </div>
    <div class="url-line">{{ displayUrl }}</div>
    <p v-if="item.snippet" class="snippet">{{ item.snippet }}</p>
    <div class="meta-line">
      <span v-for="s in item.sources" :key="s.engine" class="source-badge">{{ s.engine }}</span>
      <span v-if="item.sources.length > 1" class="multi-source">多源验证</span>
      <button class="block-btn" :title="`屏蔽 ${item.domain}（存本地，可随时撤销）`" @click="block">
        屏蔽此站点
      </button>
    </div>
  </article>
</template>

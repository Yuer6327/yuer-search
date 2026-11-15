<script setup lang="ts">
import { computed } from 'vue'
import { PhArrowUpRight, PhMinusCircle } from '@phosphor-icons/vue'
import { blockDomain } from '@/lib/prefs'
import type { RankedItem } from '@/lib/types'

const props = defineProps<{ item: RankedItem }>()
const emit = defineEmits<{ changed: [] }>()

const domain = computed(() => props.item.domain.replace(/^www\./, ''))

function block(): void {
  if (blockDomain(props.item.domain)) emit('changed')
}
</script>

<template>
  <article class="result-item">
    <div class="url-line">{{ domain }}</div>
    <h2 class="title-line">
      <a class="title" :href="item.url" target="_blank" rel="noopener">
        {{ item.title }}
        <PhArrowUpRight class="result-arrow" :size="18" weight="light" aria-hidden="true" />
      </a>
    </h2>
    <p v-if="item.snippet" class="snippet">{{ item.snippet }}</p>
    <div class="meta-line">
      <span class="source-list">{{ item.sources.map((s) => s.engine).join(' / ') }}</span>
      <span v-if="item.sources.length > 1" class="multi-source">多源收录</span>
      <button class="block-btn" :title="`屏蔽 ${item.domain}，可在偏好设置中撤销`" @click="block">
        <PhMinusCircle :size="15" weight="light" aria-hidden="true" />
        <span>屏蔽此站点</span>
      </button>
    </div>
  </article>
</template>

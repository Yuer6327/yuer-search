<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{ initial?: string; large?: boolean }>()
const router = useRouter()
const q = ref(props.initial ?? '')

watch(
  () => props.initial,
  (v) => {
    q.value = v ?? ''
  },
)

function submit(): void {
  const query = q.value.trim()
  if (!query) return
  const mode = router.currentRoute.value.query.mode ?? 'agg'
  router.push({ path: '/search', query: { q: query, mode } })
}
</script>

<template>
  <form class="searchbox" :class="{ large }" @submit.prevent="submit">
    <input
      v-model="q"
      type="search"
      placeholder="搜索"
      aria-label="搜索"
      enterkeyhint="search"
      autocomplete="off"
      spellcheck="false"
    />
    <button class="go" type="submit">搜索</button>
  </form>
</template>

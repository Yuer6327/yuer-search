<script setup lang="ts">
import { PhSlidersHorizontal } from '@phosphor-icons/vue'
import SearchBar from '@/components/SearchBar.vue'
import { openSettings } from '@/lib/ui'
</script>

<template>
  <main class="home">
    <button class="settings-link" title="搜索偏好设置" @click="openSettings">
      <PhSlidersHorizontal :size="18" weight="light" aria-hidden="true" />
      <span>偏好设置</span>
    </button>
    <section class="home-content" aria-labelledby="home-title">
      <h1 id="home-title" class="home-title">
        Yuer Search<span class="title-comma">,</span><br />
        <span class="title-secondary">Your Search</span>
      </h1>
      <SearchBar large />
    </section>
  </main>
</template>

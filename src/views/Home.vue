<script setup lang="ts">
import SearchBar from '@/components/SearchBar.vue'
import { openSettings } from '@/lib/ui'
</script>

<template>
  <main class="home">
    <h1 class="logo">Yuer 搜索</h1>
    <p class="tagline">干净 · 无广告 · 无跟踪 · 多引擎聚合 · 每用户自定义权重</p>
    <SearchBar large />
    <footer class="home-footer">
      <span>0 跟踪 · 0 广告 · 偏好仅存本地</span>
      <button @click="openSettings">设置</button>
    </footer>
  </main>
</template>

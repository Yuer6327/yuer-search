<script setup lang="ts">
import { onMounted } from 'vue'
import SettingsPanel from './components/SettingsPanel.vue'
import { ensureConfig } from './lib/googleMode'

onMounted(() => {
  void ensureConfig()
})
</script>

<template>
  <router-view />
  <SettingsPanel />
</template>

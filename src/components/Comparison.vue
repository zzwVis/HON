<script setup>
import { computed } from "vue"
import { useRegionStore } from "@/store/regionStore.js"
import RegionPanel from "./RegionPanel.vue"

const regionStore = useRegionStore()

// 只拿 region ids（轻量依赖）
const regionIds = computed(() =>
    Object.keys(regionStore.regions).filter(id => id !== "global")
)

</script>

<template>
  <div class="comparison-root">
    <div class="panel-grid">
      <RegionPanel
          v-for="rid in regionIds"
          :key="rid"
          :regionId="rid"
      />
    </div>
  </div>
</template>

<style scoped>
.comparison-root {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.panel-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: repeat(2, 1fr);
  gap: 12px;
  padding: 8px;
  height: 100%;
  overflow: auto;
}
</style>
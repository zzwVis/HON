<script setup>
import { computed } from "vue"
import { useRegionStore } from "@/store/regionStore.js"
import RegionPanel from "./RegionPanel.vue"

const regionStore = useRegionStore()

// 只拿 region ids（轻量依赖）
const regionIds = computed(() =>
    Object.keys(regionStore.regions).filter(id =>
        id !== "global" && regionStore.regions[id]?.applied
    )
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
  background:
    linear-gradient(90deg, rgba(216, 224, 234, 0.28) 1px, transparent 1px),
    linear-gradient(180deg, rgba(216, 224, 234, 0.22) 1px, transparent 1px),
    #fbfcfe;
  background-size: 28px 28px;
}

.panel-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: repeat(2, 1fr);
  gap: 9px;
  padding: 9px;
  height: 100%;
  overflow: auto;
}
</style>

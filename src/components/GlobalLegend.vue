<script setup>
import { computed, watch } from "vue"
import { usePayloadStore } from "@/store/payloadStore.js"

const payloadStore = usePayloadStore()

const tokens = computed(() => {
  const legend = payloadStore.payload?.legend
  if (!legend) return []
  return (legend.tokens || []).filter(token => token !== legend.placeholder)
})

watch(
    tokens,
    (nextTokens) => {
      if (nextTokens.length > 0) {
        payloadStore.buildGlobalColorScale(nextTokens)
      }
    },
    { immediate: true }
)

function swatchColor(token) {
  const scale = payloadStore.colorScale
  if (typeof scale !== "function") return "#94a3b8"
  return scale(String(token))
}
</script>

<template>
  <div v-if="tokens.length" class="global-legend">
    <div
        v-for="token in tokens"
        :key="token"
        class="legend-item"
    >
      <span class="swatch" :style="{ backgroundColor: swatchColor(token) }"></span>
      <span class="legend-label">{{ token }}</span>
    </div>
  </div>
</template>

<style scoped>
.global-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 18px;
  padding: 6px 8px 8px;
  border-bottom: 1px solid var(--panel-border);
  background: linear-gradient(180deg, #fbfcfe, #f2f5f8);
  color: var(--text-muted);
  font-size: 11px;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.legend-label {
  line-height: 1;
}

.swatch {
  width: 12px;
  height: 12px;
  border: 1px solid rgba(36, 49, 66, 0.32);
  box-sizing: border-box;
  display: inline-block;
}
</style>

<script setup>
import { computed, ref, watch } from "vue"
import { useBrushStore } from "@/store/brushStore.js"
import { useRegionStore } from "@/store/regionStore.js"
import { usePayloadStore } from "@/store/payloadStore.js"

const brushStore = useBrushStore()
const regionStore = useRegionStore()
const payloadStore = usePayloadStore()

const activeFilter = computed(() => brushStore.activeBrush)
const preview = computed(() => brushStore.preview)
const conditionType = ref("HO_NODE")
const conditionSearch = ref("")
const sourceEditing = ref(false)
const savedFilters = computed(() =>
  Object.values(brushStore.brushes).filter(filter => filter.saved)
)

const conditionTypes = [
  { value: "HO_NODE", label: "Higher-order Node" },
  { value: "HO_EDGE", label: "Higher-order Transition" },
  { value: "STATE", label: "First-order State" },
  { value: "STATE_TRANSITION", label: "First-order Transition" }
]

const sourceOptions = computed(() => {
  return Object.values(regionStore.regions)
    .filter(r => r.id === "global" || r.applied)
    .map(r => ({
      id: r.id,
      label: regionOptionLabel(r),
      disabled: false
    }))
})

const currentSourceId = computed({
  get() {
    const id = brushStore.activePanelRegionId || "global"
    return id === "root" ? "global" : id
  },
  set(id) {
    brushStore.setActivePanelRegion(id, id === "global" ? "global" : "region")
    brushStore.commitActiveBrushToRegion()
  }
})

const sourceLabel = computed(() => {
  const id = currentSourceId.value
  if (id === "global") return "Global"
  return `Region ${id}`
})

const hoNodeOptions = computed(() => {
  const glyph = payloadStore.payload?.glyph || {}
  return Object.keys(glyph)
    .sort((a, b) => Number(a) - Number(b))
    .map(cls => ({ value: cls, label: `node ${cls}` }))
})

const hoEdgeOptions = computed(() => {
  const seen = new Set()
  const raw = payloadStore.payload?.raw_sequences || []

  raw.forEach(seq => {
    if (!Array.isArray(seq)) return
    for (let i = 0; i < seq.length - 1; i++) {
      seen.add(`node${seq[i]}→node${seq[i + 1]}`)
    }
  })

  return Array.from(seen)
    .sort()
    .map(edge => ({ value: edge, label: edge.replaceAll("node", "") }))
})

const stateOptions = computed(() => {
  const seen = new Set()
  const seqs = payloadStore.payload?.first_order_sequences || []

  seqs.forEach(seq => {
    if (!Array.isArray(seq)) return
    seq.forEach(token => seen.add(cleanToken(token)))
  })

  return Array.from(seen)
    .filter(Boolean)
    .sort()
    .map(value => ({ value, label: value }))
})

const stateTransitionOptions = computed(() => {
  const seen = new Set()
  const seqs = payloadStore.payload?.first_order_sequences || []

  seqs.forEach(seq => {
    if (!Array.isArray(seq)) return
    const cleaned = seq.map(cleanToken)
    for (let i = 0; i < cleaned.length - 1; i++) {
      if (cleaned[i] && cleaned[i + 1]) {
        seen.add(`${cleaned[i]}→${cleaned[i + 1]}`)
      }
    }
  })

  return Array.from(seen)
    .sort()
    .map(value => ({ value, label: value }))
})

const presetOptions = computed(() => {
  if (conditionType.value === "HO_NODE") return hoNodeOptions.value
  if (conditionType.value === "HO_EDGE") return hoEdgeOptions.value
  if (conditionType.value === "STATE") return stateOptions.value
  if (conditionType.value === "STATE_TRANSITION") return stateTransitionOptions.value
  return []
})

watch(conditionType, () => {
  conditionSearch.value = ""
})

const filteredPresetOptions = computed(() => {
  const q = conditionSearch.value.trim().toLowerCase()
  if (!q) return presetOptions.value.slice(0, 80)

  return presetOptions.value
    .filter(option =>
      option.label.toLowerCase().includes(q) ||
      String(option.value).toLowerCase().includes(q)
    )
    .slice(0, 120)
})

const conditionGroups = computed(() => {
  const b = activeFilter.value
  if (!b) return []

  const groups = []

  if (b.classes?.size) {
    groups.push({
      key: "classes",
      type: "Higher-order Node",
      logic: b.groupLogic?.classes || "AND",
      values: Array.from(b.classes).map(cls => ({
        value: String(cls),
        label: `node ${cls}`
      }))
    })
  }

  if (b.edges?.length) {
    groups.push({
      key: "edges",
      type: "Higher-order Transition",
      logic: b.groupLogic?.edges || "AND",
      values: b.edges.map(edge => ({
        value: edge,
        label: edge.replaceAll("node", "")
      }))
    })
  }

  const stateValues = Array.from(b.states || []).filter(state => !String(state).includes("→"))
  const stateTransitionValues = Array.from(b.states || []).filter(state => String(state).includes("→"))

  if (stateValues.length) {
    groups.push({
      key: "states",
      type: "First-order State",
      logic: b.groupLogic?.states || "AND",
      values: stateValues.map(state => ({
        value: String(state),
        label: String(state)
      }))
    })
  }

  if (stateTransitionValues.length) {
    groups.push({
      key: "stateTransitions",
      type: "First-order Transition",
      logic: b.groupLogic?.stateTransitions || "AND",
      values: stateTransitionValues.map(state => ({
        value: String(state),
        label: String(state)
      }))
    })
  }

  return groups
})

const canPreview = computed(() => Boolean(activeFilter.value))
const canApply = computed(() =>
  Boolean(
    activeFilter.value &&
    conditionGroups.value.length > 0 &&
    preview.value?.brushId === activeFilter.value.id &&
    Number(preview.value?.count || 0) > 0
  )
)

function startBlankFilter() {
  brushStore.setActivePanelRegion("global", "global")
  brushStore.createBrush()
}

function setInteractionMode(mode) {
  brushStore.setInteractionMode(mode)
}

function cleanToken(token) {
  return String(token ?? "").replace(/[()']/g, "").trim()
}

function isPresetSelected(value) {
  const filter = activeFilter.value
  if (!filter) return false

  if (conditionType.value === "HO_NODE") {
    return filter.classes?.has(String(value))
  }

  if (conditionType.value === "HO_EDGE") {
    return filter.edges?.includes(value)
  }

  return filter.states?.has(String(value))
}

function togglePreset(value) {
  if (!activeFilter.value) startBlankFilter()

  if (isPresetSelected(value)) {
    if (conditionType.value === "HO_NODE") {
      brushStore.removeGroupValue("classes", value)
    } else if (conditionType.value === "HO_EDGE") {
      brushStore.removeGroupValue("edges", value)
    } else if (conditionType.value === "STATE_TRANSITION") {
      brushStore.removeGroupValue("stateTransitions", value)
    } else {
      brushStore.removeGroupValue("states", value)
    }
    return
  }

  if (conditionType.value === "HO_NODE") {
    brushStore.addClass(value)
  } else if (conditionType.value === "HO_EDGE") {
    brushStore.addEdge(value)
  } else {
    brushStore.addState(value)
  }
}

function toggleGroupLogic(group) {
  brushStore.setGroupLogic(group.key, group.logic === "AND" ? "OR" : "AND")
}

function removeGroup(group) {
  brushStore.clearGroup(group.key)
}

function removeGroupValue(group, value) {
  brushStore.removeGroupValue(group.key, value)
}

function regionOptionLabel(region) {
  if (region.id === "global") return "Global View"
  const brush = region.brushId ? brushStore.brushes[region.brushId] : null
  const count = Array.isArray(region.sequenceIds) ? region.sequenceIds.length : 0
  const filterName = brush?.name ? ` · ${brush.name}` : ""
  const countText = region.applied ? ` · ${count} seqs` : " · empty"
  return `Region ${region.id}${filterName}${countText}`
}

function editSavedFilter(id) {
  brushStore.setActiveBrush(id)
}

function copySavedFilter(id) {
  const nextId = brushStore.createBrushFromTemplate(id)
  if (nextId) {
    brushStore.commitActiveBrushToRegion()
  }
}

function regionIdForFilter(filterId) {
  const found = Object.values(regionStore.regions).find(region =>
    region.id !== "global" &&
    region.id !== "root" &&
    region.applied &&
    region.brushId === filterId
  )
  return found?.id || null
}

function regionLabelForFilter(filterId) {
  const rid = regionIdForFilter(filterId)
  return rid ? `Region ${rid}` : "No view"
}

function applyFilter() {
  if (!canApply.value) return
  const filterId = brushStore.saveActiveBrush()
  if (!filterId) return
  const existingRid = regionIdForFilter(filterId)
  const targetRid = existingRid || regionStore.fork()
  if (!targetRid) return

  applyPreviewToRegion(targetRid, filterId)
  if (regionStore.activeRegionId !== targetRid) {
    regionStore.setActive(targetRid)
  }
  brushStore.setActiveBrush(filterId)
  brushStore.setInteractionMode("inspect")
  brushStore.clearPreview()
}

function applyPreviewToRegion(targetRid, filterId = brushStore.activeBrushId) {
  regionStore.assignBrush(targetRid, filterId)
  brushStore.applyPreviewToSelectedRegion(targetRid)
  regionStore.applyRegion(targetRid)

  const sourceRid = preview.value?.sourceRid
  if (sourceRid) regionStore.setHighlightData(sourceRid, null, null)
  brushStore.clearPreview()
}

function clearDraft() {
  const sourceRid = preview.value?.sourceRid
  if (sourceRid) regionStore.setHighlightData(sourceRid, null, null)
  const activeId = brushStore.activeBrushId
  const active = activeFilter.value
  if (!activeId || !active) return

  if (active.saved) {
    regionStore.removeRegionsByBrush(activeId)
    brushStore.removeBrush(activeId)
  } else {
    brushStore.removeBrush(activeId)
  }
}

function removeFilter(id) {
  regionStore.removeRegionsByBrush(id)
  brushStore.removeBrush(id)
}
</script>

<template>
  <aside class="filter-panel">
    <section class="definition">
      <div class="panel-title">
        <div>
          <div class="eyebrow">Filter Definition</div>
        </div>
        <div class="mode-toggle" title="Choose whether graph clicks inspect nodes or select filter conditions">
          <button
            :class="{ active: brushStore.interactionMode === 'inspect' }"
            title="Inspect mode"
            @click="setInteractionMode('inspect')"
          >
            View
          </button>
          <button
            :class="{ active: brushStore.interactionMode === 'brush' }"
            title="Select mode"
            @click="setInteractionMode('brush')"
          >
            Select
          </button>
        </div>
      </div>

      <div class="draft-card" :class="{ empty: !activeFilter }">
        <template v-if="activeFilter">
          <div class="draft-header">
            <span class="dot" :style="{ background: activeFilter.color }" />
            <div class="draft-name">
              <strong>{{ activeFilter.name }}</strong>
              <button
                v-if="!sourceEditing"
                class="source-link"
                title="Change filter source"
                @click="sourceEditing = true"
              >
                Source: {{ sourceLabel }}
              </button>
              <select
                v-else
                v-model="currentSourceId"
                class="inline-source-select"
                @change="sourceEditing = false"
                @blur="sourceEditing = false"
              >
                <option
                  v-for="option in sourceOptions"
                  :key="option.id"
                  :value="option.id"
                  :disabled="option.disabled"
                >
                  {{ option.label }}
                </option>
              </select>
            </div>
          </div>

          <div class="condition-builder">
            <div class="builder-head">
              <label>Condition Builder</label>
            </div>
            <select v-model="conditionType">
              <option
                v-for="type in conditionTypes"
                :key="type.value"
                :value="type.value"
              >
                {{ type.label }}
              </option>
            </select>

            <input
              v-model="conditionSearch"
              placeholder="Search candidates..."
            />

            <div class="checkbox-list">
              <label
                v-for="option in filteredPresetOptions"
                :key="option.value"
                class="check-row"
              >
                <input
                  type="checkbox"
                  :checked="isPresetSelected(option.value)"
                  @change="togglePreset(option.value)"
                />
                <span>{{ option.label }}</span>
              </label>
              <div v-if="!filteredPresetOptions.length" class="no-options">
                No matching candidates.
              </div>
            </div>

          </div>

          <div class="groups">
            <div v-if="!conditionGroups.length" class="empty-state">
              Select in a view or choose candidates from the checkbox list.
            </div>

            <div
              v-for="(group, index) in conditionGroups"
              :key="group.type"
              class="group-card"
            >
              <div class="group-head">
                <span>Group {{ index + 1 }}</span>
                <span class="group-actions">
                  <button class="logic" @click="toggleGroupLogic(group)">
                    {{ group.logic }}
                  </button>
                  <button class="remove-group" title="Remove group" @click="removeGroup(group)">x</button>
                </span>
              </div>
              <div class="group-type">{{ group.type }}</div>
              <div class="chips">
                <span
                  v-for="item in group.values"
                  :key="item.value"
                  class="chip"
                >
                  <span :title="item.label">{{ item.label }}</span>
                  <button
                    class="chip-remove"
                    title="Remove condition"
                    @click="removeGroupValue(group, item.value)"
                  >
                    x
                  </button>
                </span>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="empty-state">
            <p>Switch to Select mode to create a new filter.</p>
          </div>
        </template>
      </div>

      <div class="preview-actions">
        <div class="preview-box" :class="{ active: preview?.count > 0 }">
          <span>Preview</span>
          <strong>{{ preview?.count || 0 }} seqs</strong>
        </div>

        <div class="actions">
          <button :disabled="!canApply" @click="applyFilter">
            Apply
          </button>
          <button :disabled="!canPreview" @click="clearDraft">
            Clear
          </button>
        </div>
      </div>
    </section>

    <section class="saved">
      <div class="saved-title">
        <span>Saved Filters</span>
        <span>{{ savedFilters.length }}</span>
      </div>

      <div v-if="!savedFilters.length" class="empty-list">
        No saved filters yet.
      </div>

      <div
        v-for="filter in savedFilters"
        :key="filter.id"
        class="saved-row"
        :class="{ active: filter.id === brushStore.activeBrushId }"
        title="Edit this filter"
        @click="editSavedFilter(filter.id)"
      >
        <span class="dot" :style="{ background: filter.color }" />
        <div class="saved-meta">
          <strong>{{ filter.name }}</strong>
          <span>
            {{ filter.edges.length }} edges,
            {{ filter.classes.size }} nodes,
            {{ filter.states.size }} states
          </span>
          <em>{{ regionLabelForFilter(filter.id) }}</em>
        </div>
        <button class="copy-btn" title="Copy filter" @click.stop="copySavedFilter(filter.id)">+</button>
        <button class="delete-btn" @click.stop="removeFilter(filter.id)">x</button>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.filter-panel {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px;
  background: var(--panel-bg);
  color: var(--text-main);
  font-size: 11px;
}

.definition,
.saved {
  border: 1px solid var(--panel-border);
  border-radius: 7px;
  background: #fff;
  overflow: hidden;
}

.definition {
  flex: 1.3;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.saved {
  flex: 0.9;
  min-height: 170px;
  overflow: auto;
}

.panel-title,
.saved-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  background: linear-gradient(180deg, #fbfcfe, #f2f5f8);
  border-bottom: 1px solid var(--panel-border);
}

.eyebrow {
  color: var(--text-main);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.icon-btn {
  width: 18px;
  height: 18px;
  padding: 0;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}

.mode-toggle {
  display: inline-flex;
  align-items: center;
  padding: 1px;
  border: 1px solid var(--panel-border);
  border-radius: 5px;
  background: #fff;
  gap: 1px;
}

.mode-toggle button {
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 4px;
}

.mode-toggle button.active {
  background: var(--accent);
  color: #fff;
}

.draft-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: auto;
  padding: 8px;
  background:
    linear-gradient(90deg, rgba(216, 224, 234, 0.26) 1px, transparent 1px),
    linear-gradient(180deg, rgba(216, 224, 234, 0.2) 1px, transparent 1px),
    #fbfcfe;
  background-size: 24px 24px;
}

.draft-card.empty {
  justify-content: center;
}

.draft-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 9px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex: 0 0 auto;
  box-shadow: 0 0 0 2px #fff, 0 0 0 3px rgba(36, 49, 66, 0.12);
}

.draft-name,
.saved-meta {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.draft-name strong,
.saved-meta strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.draft-name span,
.saved-meta span {
  color: var(--text-muted);
  font-size: 10px;
}

.source-link {
  width: fit-content;
  max-width: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 10px;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-link:hover {
  color: var(--accent);
  background: transparent;
  text-decoration: underline;
}

.inline-source-select {
  width: 100%;
  min-height: 24px;
  border: 1px solid var(--panel-border);
  border-radius: 5px;
  background: #fff;
  color: var(--text-main);
  padding: 0 6px;
  font: inherit;
  font-size: 11px;
}

.condition-builder {
  display: grid;
  gap: 6px;
  margin-bottom: 9px;
  padding: 8px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.92);
}

.builder-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.condition-builder label {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
}

.condition-builder select,
.condition-builder input {
  width: 100%;
  min-height: 27px;
  border: 1px solid var(--panel-border);
  border-radius: 5px;
  background: var(--panel-soft);
  color: var(--text-main);
  padding: 0 7px;
  font: inherit;
  font-size: 11px;
}

.condition-builder input:focus,
.condition-builder select:focus {
  outline: 2px solid rgba(47, 111, 159, 0.18);
  border-color: rgba(47, 111, 159, 0.55);
  background: #fff;
}

.condition-builder button {
  min-height: 22px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.checkbox-list {
  max-height: 76px;
  overflow: auto;
  display: grid;
  gap: 2px;
  padding: 4px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: #fff;
}

.check-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 5px;
  border-radius: 4px;
  cursor: pointer;
}

.check-row:hover {
  background: var(--accent-soft);
}

.check-row input {
  width: auto;
  min-height: 0;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  accent-color: var(--accent);
}

.check-row span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.no-options {
  padding: 8px 4px;
  color: var(--text-muted);
  text-align: center;
}

.groups {
  display: grid;
  gap: 8px;
}

.group-card {
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.92);
  padding: 8px;
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
}

.group-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.logic,
.remove-group {
  min-height: 20px;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 700;
  border-color: transparent;
  background: transparent;
}

.logic {
  color: var(--accent);
  border-color: rgba(47, 111, 159, 0.24);
  background: var(--accent-soft);
}

.remove-group {
  color: #9a3340;
}

.group-type {
  margin-top: 3px;
  font-weight: 700;
}

.chips {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 5px;
  margin-top: 7px;
  min-width: 0;
}

.chip {
  max-width: 100%;
  min-width: 0;
  padding: 2px 4px 2px 6px;
  border: 1px solid #dce5ee;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--text-main);
  display: inline-flex;
  align-items: center;
  gap: 2px;
  overflow: hidden;
}

.chip > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-remove {
  flex: 0 0 auto;
  width: 12px;
  height: 12px;
  min-height: 12px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #7d8792;
  font-size: 10px;
  line-height: 1;
}

.chip-remove:hover {
  color: #9a3340;
}

.empty-state,
.empty-list {
  padding: 12px;
  color: var(--text-muted);
  text-align: center;
  line-height: 1.35;
}

.preview-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 9px 8px;
}

.preview-box {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 28px;
  padding: 5px 7px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: var(--panel-soft);
  color: var(--text-muted);
  font-size: 10px;
}

.preview-box.active {
  color: var(--text-main);
  border-color: rgba(47, 111, 159, 0.45);
  background: var(--accent-soft);
}

.actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.actions button {
  min-width: 46px;
  min-height: 28px;
  padding: 4px 8px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.actions button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  background: #f3f5f8;
  color: var(--text-muted);
  border-color: var(--panel-border);
}

.saved-title {
  font-weight: 700;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.saved-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 9px;
  border-bottom: 1px solid #edf1f5;
  cursor: pointer;
}

.saved-row:hover,
.saved-row.active {
  background: var(--accent-soft);
}

.saved-row.active {
  box-shadow: inset 3px 0 0 var(--accent);
}

.saved-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.saved-meta em {
  color: var(--accent);
  font-style: normal;
}

.copy-btn,
.delete-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  font-size: 10px;
  font-weight: 700;
  border-color: transparent;
  background: transparent;
}

.copy-btn {
  color: var(--accent);
}

.delete-btn {
  color: #9a3340;
}
</style>

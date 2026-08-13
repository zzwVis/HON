<script setup>
import { computed, ref } from "vue"
import { usePayloadStore } from "@/store/payloadStore.js"
import { useBrushStore } from "@/store/brushStore.js"
import { useRegionStore } from "@/store/regionStore.js"
import { computeMemorySplits } from "@/composables/memorySplits.js"

const payloadStore = usePayloadStore()
const brushStore = useBrushStore()
const regionStore = useRegionStore()
const expandedContexts = ref(new Set())
const expandedContextGroups = ref(new Set())
const foContextSortDescending = ref(true)
const hoMemberSortDescending = ref(true)
const foNextEventFocus = ref(null)

const selectionRegionId = computed(() => {
  if (payloadStore.selectedHighOrderClass != null) {
    return payloadStore.selectedHighOrderRegionId || "global"
  }
  if (payloadStore.selectedFirstOrderState != null) {
    return payloadStore.selectedFirstOrderRegionId || "global"
  }
  return regionStore.activeRegionId || "global"
})

const activePayload = computed(() => {
  const rid = selectionRegionId.value
  const region = rid ? regionStore.regions[rid] : null
  return region?.modelPayload || payloadStore.payload
})

function normalizeToken(x) {
  return String(x ?? "")
      .trim()
      .replace(/^['"]|['"]$/g, "")
      .replace(/[']/g, "")
}

function sameToken(a, b) {
  return normalizeToken(a) === normalizeToken(b)
}

function displayToken(token, legend) {
  const raw = String(token ?? "").trim()
  const tokenList = Array.isArray(legend?.tokens) ? legend.tokens : []
  const hit = tokenList.find(t => sameToken(t, raw))
  return hit || raw
}

function tokenColor(token) {
  const scale = payloadStore.colorScale
  if (typeof scale !== "function") return "#94a3b8"
  return scale(String(token))
}

function stateKey(tokens) {
  return (tokens || []).map(v => String(v)).join("→")
}

function compactLabel(label, maxLen = 20) {
  const text = String(label ?? "")
  return text.length > maxLen ? `${text.slice(0, maxLen)}…` : text
}

function addCount(map, key, amount = 1) {
  map.set(key, (map.get(key) || 0) + amount)
}

function entropy(counts) {
  const total = Array.from(counts.values()).reduce((a, b) => a + b, 0)
  if (total <= 0 || counts.size <= 1) return 0
  const h = Array.from(counts.values()).reduce((sum, c) => {
    const p = c / total
    return p > 0 ? sum - p * Math.log2(p) : sum
  }, 0)
  return h / Math.log2(counts.size)
}

function toProbMap(counts) {
  const total = Array.from(counts.values()).reduce((a, b) => a + b, 0)
  const probs = new Map()
  if (total <= 0) return probs
  counts.forEach((value, key) => probs.set(key, value / total))
  return probs
}

function countTotal(counts) {
  return Array.from(counts?.values?.() || []).reduce((a, b) => a + b, 0)
}

function klDivergence(sourceCounts, baselineCounts) {
  // No outgoing transitions means there is no next-step distribution to compare.
  if (countTotal(sourceCounts) <= 0 || countTotal(baselineCounts) <= 0) return 0

  const p = toProbMap(sourceCounts)
  const q = toProbMap(baselineCounts)
  const keys = Array.from(new Set([...p.keys(), ...q.keys()]))
  if (!keys.length) return 0

  const epsilon = 1e-6
  const smoothDenominator = 1 + epsilon * keys.length

  const value = keys.reduce((sum, key) => {
    const pv = ((p.get(key) || 0) + epsilon) / smoothDenominator
    const qv = ((q.get(key) || 0) + epsilon) / smoothDenominator
    return sum + pv * Math.log2(pv / qv)
  }, 0)

  if (Math.abs(value) < 1e-10) return 0
  return Math.max(0, value)
}

function buildStateSummary(seqs, selectedState) {
  const nextCounts = new Map()
  const supportSeqIds = new Set()
  let occurrences = 0

  seqs.forEach((seq, sid) => {
    let hit = false
    for (let i = 0; i < seq.length; i++) {
      if (!sameToken(seq[i], selectedState)) continue
      occurrences += 1
      hit = true
      if (i < seq.length - 1) addCount(nextCounts, normalizeToken(seq[i + 1]))
    }
    if (hit) supportSeqIds.add(sid)
  })

  return {
    occurrences,
    sequenceSupport: supportSeqIds.size,
    nextCounts,
    entropy: entropy(nextCounts)
  }
}

function matchesStateAt(seq, start, tokens) {
  if (start < 0 || start + tokens.length > seq.length) return false
  for (let i = 0; i < tokens.length; i++) {
    if (!sameToken(seq[start + i], tokens[i])) return false
  }
  return true
}

function countContextOccurrences(seqs, tokens) {
  const nextCounts = new Map()
  const supportSeqIds = new Set()
  let occurrences = 0

  seqs.forEach((seq, sid) => {
    let hit = false
    for (let i = 0; i <= seq.length - tokens.length; i++) {
      if (!matchesStateAt(seq, i, tokens)) continue
      occurrences += 1
      hit = true
      const next = seq[i + tokens.length]
      if (next != null) addCount(nextCounts, normalizeToken(next))
    }
    if (hit) supportSeqIds.add(sid)
  })

  return {
    occurrences,
    sequenceSupport: supportSeqIds.size,
    nextCounts,
    entropy: entropy(nextCounts)
  }
}

function countClusterOccurrences(classSeqs, firstSeqs, classId) {
  const nextCounts = new Map()
  const supportSeqIds = new Set()
  let occurrences = 0

  ;(classSeqs || []).forEach((seq, sid) => {
    const firstSeq = firstSeqs?.[sid] || []
    let hit = false
    for (let i = 0; i < seq.length; i++) {
      if (String(seq[i]) !== String(classId)) continue
      occurrences += 1
      hit = true
      const next = firstSeq[i + 1]
      if (next != null) addCount(nextCounts, normalizeToken(next))
    }
    if (hit) supportSeqIds.add(sid)
  })

  return {
    occurrences,
    sequenceSupport: supportSeqIds.size,
    nextCounts,
    entropy: entropy(nextCounts)
  }
}

function buildBars(counts, legend) {
  const total = Array.from(counts.values()).reduce((a, b) => a + b, 0)
  return Array.from(counts.entries())
      .filter(([, count]) => count > 0 && total > 0)
      .map(([token, count]) => ({
        token,
        label: displayToken(token, legend),
        count,
        prob: total > 0 ? count / total : 0
      }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

function contextBarForEvent(context, eventName) {
  if (!context || eventName == null) return null
  return (context.bars || []).find(bar => sameToken(bar.token, eventName)) || null
}

function visibleMemberStates(glyph) {
  return Array.isArray(glyph?.full_order_states) ? glyph.full_order_states : (glyph?.unique_states || [])
}

const selectedLabel = computed(() => {
  return payloadStore.selectedFirstOrderState
      ? displayToken(payloadStore.selectedFirstOrderState, activePayload.value?.legend)
      : null
})

const selectedStateColor = computed(() => {
  return payloadStore.selectedFirstOrderState
      ? tokenColor(payloadStore.selectedFirstOrderState)
      : "#94a3b8"
})

const selectedHighOrderLabel = computed(() => {
  return payloadStore.selectedHighOrderClass ? `HO Node ${payloadStore.selectedHighOrderClass}` : null
})

const inspector = computed(() => {
  const payload = activePayload.value
  const selectedState = payloadStore.selectedFirstOrderState
  const seqs = payload?.first_order_sequences || []
  if (!payload || !selectedState || seqs.length === 0) return null

  const summary = buildStateSummary(seqs, selectedState)
  const contexts = []

  Object.entries(payload.glyph || {}).forEach(([classId, glyph]) => {
    visibleMemberStates(glyph).forEach(tokens => {
      if (!tokens.length || !sameToken(tokens[tokens.length - 1], selectedState)) return
      const counts = countContextOccurrences(seqs, tokens)
      if (counts.occurrences === 0) return
      contexts.push({
        classId: String(classId),
        key: stateKey(tokens),
        tokens,
        label: tokens.map(t => displayToken(t, payload.legend)).join(" → "),
        tokenItems: tokens.map(t => {
          const label = displayToken(t, payload.legend)
          return {
            raw: String(t),
            label,
            color: tokenColor(t)
          }
        }),
        occurrences: counts.occurrences,
        sequenceSupport: counts.sequenceSupport,
        entropy: counts.entropy,
        divergence: klDivergence(counts.nextCounts, summary.nextCounts),
        bars: buildBars(counts.nextCounts, payload.legend)
      })
    })
  })

  contexts.sort((a, b) =>
      b.divergence - a.divergence ||
      b.sequenceSupport - a.sequenceSupport ||
      b.occurrences - a.occurrences
  )

  const focusedNextEvent = Array.from(summary.nextCounts.keys())
      .find(token => sameToken(token, foNextEventFocus.value)) || null
  const contextsForEvent = focusedNextEvent
      ? contexts.filter(context => contextBarForEvent(context, focusedNextEvent))
      : contexts

  const hoNodeCounts = new Map()
  contextsForEvent.forEach(context => {
    hoNodeCounts.set(context.classId, (hoNodeCounts.get(context.classId) || 0) + 1)
  })
  const hoNodeDistribution = Array.from(hoNodeCounts.entries())
      .map(([classId, count]) => ({
        classId,
        label: `HO Node ${classId}`,
        count,
        isOther: false
      }))
      .sort((a, b) => b.count - a.count || Number(a.classId) - Number(b.classId))
  const shownHoNodeDistribution = hoNodeDistribution.slice(0, 3)
  const otherHoNodeCount = hoNodeDistribution.slice(3).reduce((sum, item) => sum + item.count, 0)
  if (otherHoNodeCount > 0) {
    shownHoNodeDistribution.push({
      classId: null,
      label: "Others",
      count: otherHoNodeCount,
      isOther: true
    })
  }

  const orderedContexts = foContextSortDescending.value
      ? contextsForEvent
      : [...contextsForEvent].sort((a, b) =>
          a.divergence - b.divergence ||
          b.sequenceSupport - a.sequenceSupport ||
          b.occurrences - a.occurrences
      )

  const visibleContexts = orderedContexts.slice(0, 24)
  const contextGroupMap = new Map()
  visibleContexts.forEach(context => {
    if (!contextGroupMap.has(context.classId)) {
      contextGroupMap.set(context.classId, {
        classId: context.classId,
        contexts: [],
        maxDivergence: 0,
        maxSequenceSupport: 0,
        occurrences: 0
      })
    }
    const group = contextGroupMap.get(context.classId)
    group.contexts.push(context)
    group.maxDivergence = Math.max(group.maxDivergence, context.divergence)
    group.maxSequenceSupport = Math.max(group.maxSequenceSupport, context.sequenceSupport)
    group.occurrences += context.occurrences
  })

  const contextGroups = Array.from(contextGroupMap.values()).sort((a, b) =>
      b.maxDivergence - a.maxDivergence ||
      b.maxSequenceSupport - a.maxSequenceSupport ||
      b.occurrences - a.occurrences
  )

  return {
    ...summary,
    bars: buildBars(summary.nextCounts, payload.legend),
    contexts: visibleContexts,
    contextGroups,
    focusedNextEvent,
    focusedNextEventLabel: focusedNextEvent ? displayToken(focusedNextEvent, payload.legend) : null,
    matchingContextCount: contextsForEvent.length,
    totalContextCount: contexts.length,
    hoNodeDistribution: shownHoNodeDistribution,
    hoNodeDistributionTitle: focusedNextEvent
        ? `${displayToken(focusedNextEvent, payload.legend)}-related states:`
        : "All ending states:"
  }
})

const highOrderInspector = computed(() => {
  const payload = activePayload.value
  const classId = payloadStore.selectedHighOrderClass
  const seqs = payload?.first_order_sequences || []
  const classSeqs = payload?.raw_sequences || []
  const glyph = classId != null ? payload?.glyph?.[String(classId)] : null
  if (!payload || classId == null || !glyph || seqs.length === 0) return null

  const cluster = countClusterOccurrences(classSeqs, seqs, classId)
  const members = visibleMemberStates(glyph).map(tokens => {
    const counts = countContextOccurrences(seqs, tokens)
    const divergence = klDivergence(counts.nextCounts, cluster.nextCounts)
    return {
      key: stateKey(tokens),
      tokens,
      label: tokens.map(t => displayToken(t, payload.legend)).join(" → "),
      tokenItems: tokens.map(t => ({
        raw: String(t),
        label: displayToken(t, payload.legend),
        color: tokenColor(t)
      })),
      occurrences: counts.occurrences,
      sequenceSupport: counts.sequenceSupport,
      entropy: counts.entropy,
      divergence,
      bars: buildBars(counts.nextCounts, payload.legend)
    }
  }).filter(member => member.occurrences > 0)

  members.sort((a, b) =>
      b.divergence - a.divergence ||
      b.sequenceSupport - a.sequenceSupport ||
      b.occurrences - a.occurrences
  )

  if (!hoMemberSortDescending.value) {
    members.sort((a, b) =>
        a.divergence - b.divergence ||
        b.sequenceSupport - a.sequenceSupport ||
        b.occurrences - a.occurrences
    )
  }

  const internalConsistency =
      members.length > 0
          ? members.reduce((sum, member) => sum + member.divergence, 0) / members.length
          : 0

  return {
    classId: String(classId),
    support: cluster.sequenceSupport,
    occurrences: cluster.occurrences,
    entropy: cluster.entropy,
    internalConsistency,
    bars: buildBars(cluster.nextCounts, payload.legend),
    members
  }
})

const memorySplits = computed(() => computeMemorySplits(activePayload.value))

function formatPct(v) {
  return `${(v * 100).toFixed(2)}%`
}

function barWidth(v) {
  return `${Math.max(0, Math.min(100, v * 100))}%`
}

function isContextExpanded(key) {
  return expandedContexts.value.has(key)
}

function toggleContextExpanded(key) {
  const next = new Set(expandedContexts.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedContexts.value = next
}

function isContextGroupExpanded(classId) {
  return expandedContextGroups.value.has(String(classId))
}

function toggleContextGroupExpanded(classId) {
  const key = String(classId)
  const next = new Set(expandedContextGroups.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedContextGroups.value = next
}

function ensureFilterForActiveRegion() {
  const rid = selectionRegionId.value || regionStore.activeRegionId || "global"
  if (!brushStore.activeBrush) {
    brushStore.setActivePanelRegion(rid, rid === "global" ? "global" : "region")
    brushStore.createBrush()
  }
  return rid
}

function addSelectedStateToFilter() {
  const state = payloadStore.selectedFirstOrderState
  if (!state) return
  ensureFilterForActiveRegion()
  brushStore.addState(String(state))
}

function addSelectedHighOrderToFilter() {
  const classId = payloadStore.selectedHighOrderClass
  if (classId == null) return
  ensureFilterForActiveRegion()
  brushStore.addClass(String(classId))
}

function addContextToFilter(context) {
  if (!context) return
  ensureFilterForActiveRegion()
  brushStore.addState(context.key)
}

function addContextGroupToFilter(group) {
  if (!group) return
  ensureFilterForActiveRegion()
  brushStore.addClass(group.classId)
}

function addMemberToFilter(member) {
  if (!member) return
  ensureFilterForActiveRegion()
  brushStore.addState(member.key)
}

function setAppendHover(bar) {
  payloadStore.setHoveredAppendEvent(null)
}

function clearAppendHover() {
  payloadStore.setHoveredAppendEvent(null)
}

function toggleAppendFocus(bar) {
  payloadStore.setFocusedAppendEvent(null)
}

function toggleFoContextSort() {
  foContextSortDescending.value = !foContextSortDescending.value
}

function toggleHoMemberSort() {
  hoMemberSortDescending.value = !hoMemberSortDescending.value
}

function isFoNextEventFocused(bar) {
  return bar && foNextEventFocus.value != null && sameToken(bar.token, foNextEventFocus.value)
}

function toggleFoNextEventFocus(bar) {
  if (!bar) return
  foNextEventFocus.value = isFoNextEventFocused(bar) ? null : String(bar.token)
}

function focusedContextEventBar(context) {
  return contextBarForEvent(context, inspector.value?.focusedNextEvent)
}

function inspectHoNodeFromSummary(item) {
  if (!item || item.isOther || item.classId == null) return
  payloadStore.setHighOrderClass(String(item.classId), selectionRegionId.value || "global")
}

function clearHighOrderHover() {
  payloadStore.setHoveredHighOrderClasses([])
}

function setContextHover(classId) {
  payloadStore.setHoveredHighOrderClasses(classId == null ? [] : [String(classId)])
}

function hoverMemorySplit(split) {
  payloadStore.setHoveredHighOrderClasses(split?.classIds || [])
}

function inspectMemorySplit(split) {
  if (!split) return
  payloadStore.setFirstOrderState(String(split.token), selectionRegionId.value || "global")
}

function setFirstOrderProjectionHover(bar, contexts) {
  const classIds = (contexts || [])
      .filter(context => contextBarForEvent(context, bar?.token))
      .map(context => String(context.classId))
  payloadStore.setHoveredHighOrderClasses(classIds)
}

function clearFirstOrderProjectionHover() {
  payloadStore.setHoveredHighOrderClasses([])
}
</script>

<template>
  <section class="state-inspector">
    <header class="panel-title">
      <span>CONTEXT INSPECTOR</span>
    </header>

    <div v-if="!inspector && !highOrderInspector" class="empty-state">
      <div v-if="!activePayload" class="small-empty">
        Select a state in the first-order network or a high-order node.
      </div>
      <template v-else>
        <div class="section-label compact-top">Memory splits</div>
        <div class="state-meta" style="margin-bottom: 8px;">
          First-order events that end in 2+ high-order nodes. Click to inspect; hover to highlight those nodes.
        </div>
        <div v-if="memorySplits.length" class="scroll-block context-block">
          <div class="context-list">
            <div
                v-for="split in memorySplits"
                :key="split.tokenKey"
                class="context-row split-row"
                @mouseenter="hoverMemorySplit(split)"
                @mouseleave="clearHighOrderHover"
                @click="inspectMemorySplit(split)"
            >
              <div class="context-summary">
                <div class="context-main">
                  <div class="context-tokens">
                    <span
                        class="token-circle"
                        :title="split.label"
                        :style="{ backgroundColor: tokenColor(split.token) }"
                    ></span>
                    <span class="split-label">{{ split.label }}</span>
                  </div>
                  <div class="context-meta">
                    {{ split.hoNodeCount }} HO nodes · max KL {{ split.maxPairKl.toFixed(3) }}
                    · {{ split.occurrences }} occ
                  </div>
                  <div v-if="split.contrast.length === 2" class="split-contrast">
                    <span v-for="side in split.contrast" :key="split.tokenKey + ':' + side.classId">
                      HO {{ side.classId }} → {{ side.nextLabel }} {{ formatPct(side.nextProb) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="small-empty">
          No first-order event is split across multiple high-order nodes. Click a state or HO node to inspect.
        </div>
      </template>
    </div>

    <template v-else-if="inspector">
      <div class="state-heading">
        <div>
          <div class="state-name-row">
            <div class="state-name">{{ selectedLabel }}</div>
            <span
                class="selected-state-dot"
                :title="selectedLabel"
                :style="{ backgroundColor: selectedStateColor }"
            ></span>
            <button class="mini-button" @click="addSelectedStateToFilter">Filter</button>
          </div>
          <div class="state-meta">
            {{ inspector.sequenceSupport }} seqs · {{ inspector.occurrences }} occurrences · entropy {{ inspector.entropy.toFixed(3) }}
          </div>
        </div>
      </div>

      <div class="section-label compact-top">Next-step distribution</div>
      <div v-if="inspector.bars.length" class="scroll-block next-step-block">
      <div class="bar-list">
        <div
            v-for="bar in inspector.bars"
            :key="bar.token"
            class="bar-row"
            :class="{ 'bar-row-active': isFoNextEventFocused(bar) }"
            :title="`Show high-order states whose next step includes ${bar.label}`"
            @click="toggleFoNextEventFocus(bar)"
        >
          <span class="bar-label">
            <span class="bar-label-text">{{ bar.label }}</span>
            <span class="next-token-dot" :title="bar.label" :style="{ backgroundColor: tokenColor(bar.token) }"></span>
          </span>
          <div class="bar-track">
            <div class="bar-fill" :style="{ width: barWidth(bar.prob) }"></div>
          </div>
          <span class="bar-value">{{ formatPct(bar.prob) }}</span>
        </div>
      </div>
      </div>
      <div v-else class="small-empty">No outgoing transition.</div>

      <div class="section-label section-label-row">
        <span>High-order states ending here</span>
        <button
            v-if="inspector.focusedNextEvent"
            class="next-event-filter-chip"
            :title="`Clear next-event focus: ${inspector.focusedNextEventLabel}`"
            @click="foNextEventFocus = null"
        >
          Next = {{ inspector.focusedNextEventLabel }} · {{ inspector.matchingContextCount }}/{{ inspector.totalContextCount }}
        </button>
        <button
            class="sort-toggle-button"
            :title="foContextSortDescending ? 'Sort KL from low to high' : 'Sort KL from high to low'"
            @click="toggleFoContextSort"
        >
          KL {{ foContextSortDescending ? '↓' : '↑' }}
        </button>
      </div>
      <div
          v-if="inspector.hoNodeDistribution.length"
          class="ho-node-summary"
      >
        <span class="ho-node-summary-title">{{ inspector.hoNodeDistributionTitle }}</span>
        <button
            v-for="item in inspector.hoNodeDistribution"
            :key="item.label"
            class="ho-node-summary-chip"
            :class="{ disabled: item.isOther }"
            :title="item.isOther ? 'Remaining HO nodes' : `Inspect ${item.label}`"
            @click="inspectHoNodeFromSummary(item)"
        >
          {{ item.label }}: {{ item.count }} {{ item.count === 1 ? 'state' : 'states' }}
        </button>
      </div>
      <div v-if="inspector.contexts.length" class="scroll-block context-block">
      <div class="context-list state-first-context-list">
        <div
            v-for="context in inspector.contexts"
            :key="context.classId + ':' + context.key"
            class="context-row state-first-context-row"
            @mouseenter="setContextHover(context.classId)"
            @mouseleave="clearHighOrderHover"
        >
          <div class="context-summary">
            <button
                class="expand-button"
                :class="{ expanded: isContextExpanded(context.key) }"
                :title="isContextExpanded(context.key) ? 'Collapse' : 'Expand'"
                @click="toggleContextExpanded(context.key)"
            >
              <span class="triangle-icon"></span>
            </button>
            <div class="context-main">
              <div class="context-tokens state-context-tokens">
                <template v-for="(token, index) in context.tokenItems" :key="context.key + ':' + index">
                  <span class="token-circle" :title="token.label" :style="{ backgroundColor: token.color }"></span>
                  <span v-if="index < context.tokenItems.length - 1" class="token-arrow">→</span>
                </template>
                <span class="ho-node-tag" :title="`This state belongs to HO Node ${context.classId}`">
                  HO Node {{ context.classId }}
                </span>
              </div>
              <div
                  class="context-meta"
                  title="KL divergence from the selected first-order state's next-step behavior."
              >
                {{ context.sequenceSupport }} seqs · KL vs selected FO {{ context.divergence.toFixed(3) }}
                <template v-if="inspector.focusedNextEvent">
                  · {{ inspector.focusedNextEventLabel }} {{ formatPct(focusedContextEventBar(context)?.prob || 0) }}
                </template>
              </div>
            </div>
            <button class="mini-button" @click="addContextToFilter(context)">Filter</button>
          </div>
          <div v-if="isContextExpanded(context.key)" class="context-detail">
            <div v-if="context.bars.length" class="context-bar-list">
              <div
                  v-for="bar in context.bars"
                  :key="context.key + ':' + bar.token"
                  class="bar-row context-bar-row"
              >
                <span class="bar-label">
                  <span class="bar-label-text" :title="bar.label">{{ compactLabel(bar.label) }}</span>
                  <span class="next-token-dot" :title="bar.label" :style="{ backgroundColor: tokenColor(bar.token) }"></span>
                </span>
                <div class="bar-track">
                  <div class="bar-fill context-bar-fill" :style="{ width: barWidth(bar.prob) }"></div>
                </div>
                <span class="bar-value">{{ formatPct(bar.prob) }}</span>
              </div>
            </div>
            <div v-else class="small-empty">No outgoing transition.</div>
          </div>
        </div>
      </div>
      </div>
      <div v-else class="small-empty">
        {{ inspector.focusedNextEvent ? 'No high-order state has this next step.' : 'No high-order state ends with this state.' }}
      </div>
    </template>

    <template v-else-if="highOrderInspector">
      <div class="state-heading">
        <div>
          <div class="state-name-row">
            <div class="state-name">{{ selectedHighOrderLabel }}</div>
            <button class="mini-button" @click="addSelectedHighOrderToFilter">Filter</button>
          </div>
          <div class="state-meta">
            {{ highOrderInspector.support }} seqs · {{ highOrderInspector.occurrences }} occurrences
          </div>
        </div>
      </div>

      <div class="summary-grid">
        <div class="summary-item">
          <span>Entropy</span>
          <b>{{ highOrderInspector.entropy.toFixed(3) }}</b>
        </div>
        <div class="summary-item">
          <span title="Average member divergence from this HO node's overall next-step distribution.">Avg KL vs node</span>
          <b>{{ highOrderInspector.internalConsistency.toFixed(3) }}</b>
        </div>
      </div>

      <div class="section-label">Next-step distribution</div>
      <div v-if="highOrderInspector.bars.length" class="scroll-block projection-block">
      <div class="bar-list">
        <div
            v-for="bar in highOrderInspector.bars"
            :key="'cluster:' + bar.token"
            class="bar-row"
        >
          <span class="bar-label">
            <span class="bar-label-text">{{ bar.label }}</span>
            <span class="next-token-dot" :title="bar.label" :style="{ backgroundColor: tokenColor(bar.token) }"></span>
          </span>
          <div class="bar-track">
            <div class="bar-fill" :style="{ width: barWidth(bar.prob) }"></div>
          </div>
          <span class="bar-value">{{ formatPct(bar.prob) }}</span>
        </div>
      </div>
      </div>
      <div v-else class="small-empty">No outgoing transition.</div>

      <div class="section-label section-label-row">
        <span>{{ highOrderInspector.members.length }} Member States</span>
        <button
            class="sort-toggle-button"
            :title="hoMemberSortDescending ? 'Sort KL from low to high' : 'Sort KL from high to low'"
            @click="toggleHoMemberSort"
        >
          KL {{ hoMemberSortDescending ? '↓' : '↑' }}
        </button>
      </div>
      <div v-if="highOrderInspector.members.length" class="scroll-block member-block">
      <div class="context-list">
        <div
            v-for="member in highOrderInspector.members"
            :key="'member:' + member.key"
            class="context-row"
        >
          <div class="context-summary">
            <button
                class="expand-button"
                :class="{ expanded: isContextExpanded(member.key) }"
                :title="isContextExpanded(member.key) ? 'Collapse' : 'Expand'"
                @click="toggleContextExpanded(member.key)"
            >
              <span class="triangle-icon"></span>
            </button>
            <div class="context-main">
              <div class="context-tokens">
                <template v-for="(token, index) in member.tokenItems" :key="member.key + ':' + index">
                  <span class="token-circle" :title="token.label" :style="{ backgroundColor: token.color }"></span>
                  <span v-if="index < member.tokenItems.length - 1" class="token-arrow">→</span>
                </template>
              </div>
              <div
                  class="context-meta"
                  title="KL divergence from this HO node's overall next-step distribution."
              >
                {{ member.sequenceSupport }} seqs · KL vs node {{ member.divergence.toFixed(3) }}
              </div>
            </div>
            <button class="mini-button" @click="addMemberToFilter(member)">Filter</button>
          </div>
          <div v-if="isContextExpanded(member.key)" class="context-detail">
            <div v-if="member.bars.length" class="context-bar-list">
              <div
                  v-for="bar in member.bars"
                  :key="member.key + ':' + bar.token"
                  class="bar-row context-bar-row"
              >
                <span class="bar-label">
                  <span class="bar-label-text" :title="bar.label">{{ compactLabel(bar.label) }}</span>
                  <span class="next-token-dot" :title="bar.label" :style="{ backgroundColor: tokenColor(bar.token) }"></span>
                </span>
                <div class="bar-track">
                  <div class="bar-fill context-bar-fill" :style="{ width: barWidth(bar.prob) }"></div>
                </div>
                <span class="bar-value">{{ formatPct(bar.prob) }}</span>
              </div>
            </div>
            <div v-else class="small-empty">No outgoing transition.</div>
          </div>
        </div>
      </div>
      </div>
      <div v-else class="small-empty">No member states available.</div>
    </template>
  </section>
</template>

<style scoped>
.state-inspector {
  width: 100%;
  height: 100%;
  padding: 10px;
  background: #fff;
  color: var(--text-main);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panel-title {
  display: flex;
  align-items: center;
  min-height: 24px;
  border-bottom: 1px solid var(--panel-border);
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 700;
  color: #111827;
  letter-spacing: 0;
}

.empty-state,
.small-empty {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.empty-state {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.split-row {
  padding-left: 7px;
  cursor: pointer;
}

.split-row:hover {
  border-color: rgba(59, 130, 246, 0.45);
  background: var(--accent-soft);
}

.split-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #111827;
  font-size: 11px;
  font-weight: 700;
}

.split-contrast {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin-top: 3px;
  font-size: 10px;
  color: var(--text-muted);
}

.state-heading {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.state-name {
  font-size: 12px;
  font-weight: 700;
  color: #111827;
}

.state-name-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.selected-state-dot {
  width: 11px;
  height: 11px;
  border-radius: 999px;
  flex: 0 0 auto;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.1);
}

.state-meta,
.context-meta {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-muted);
}

.section-label {
  margin: 5px 0 5px;
  font-size: 11px;
  font-weight: 700;
  color: #111827;
}

.section-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.sort-toggle-button {
  flex: 0 0 auto;
  padding: 1px 5px;
  border: 1px solid var(--panel-border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 9px;
  font-weight: 700;
  line-height: 1.25;
}

.sort-toggle-button:hover {
  color: var(--accent);
  border-color: rgba(59, 130, 246, 0.35);
}

.next-event-filter-chip {
  min-width: 0;
  margin-left: auto;
  padding: 1px 6px;
  border: 1px solid rgba(59, 130, 246, 0.28);
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  cursor: pointer;
  font-size: 9px;
  font-weight: 700;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ho-node-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  margin: -1px 0 5px;
  color: var(--text-muted);
  font-size: 10px;
}

.ho-node-summary-title {
  flex: 0 0 auto;
  font-weight: 700;
  color: #334155;
}

.ho-node-summary-chip {
  flex: 0 0 auto;
  padding: 1px 5px;
  border: 1px solid var(--panel-border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 9px;
  font-weight: 700;
  line-height: 1.25;
}

.ho-node-summary-chip:not(.disabled):hover {
  color: var(--accent);
  border-color: rgba(59, 130, 246, 0.35);
}

.ho-node-summary-chip.disabled {
  cursor: default;
  background: var(--panel-soft);
}

.compact-top {
  margin-top: 1px;
}

.bar-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.bar-row {
  display: grid;
  grid-template-columns: minmax(60px, 0.8fr) 1fr 48px;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  cursor: pointer;
  border-radius: 4px;
  padding: 1px 2px;
  margin: -1px -2px;
}

.bar-row-active {
  background: var(--accent-soft);
}

.bar-label {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 5px;
  overflow: hidden;
  white-space: nowrap;
}

.bar-label-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.next-token-dot {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
}

.bar-track {
  height: 7px;
  border-radius: 999px;
  background: #eef2f6;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}

.bar-value {
  text-align: right;
  color: var(--text-muted);
}

.context-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.context-group-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.context-group {
  position: relative;
  padding: 5px 7px 3px 18px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: #fff;
}

.context-group-header {
  position: static;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 3px;
  padding: 0;
  font-size: 11px;
}

.context-group-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.context-group-title {
  font-weight: 700;
  color: #334155;
}

.context-group-meta {
  min-width: 0;
  color: var(--text-muted);
  line-height: 1.1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grouped-context-list {
  gap: 4px;
}

.state-first-context-list {
  gap: 6px;
}

.state-first-context-row {
  background: #fff;
}

.group-expand-button {
  top: 6px;
  left: 3px;
}

.context-row {
  display: block;
  position: relative;
  padding: 6px 7px 6px 17px;
  border: 1px solid var(--panel-border);
  border-radius: 5px;
  background: var(--panel-soft);
}

.context-summary {
  display: flex;
  align-items: center;
  gap: 6px;
}

.context-main {
  min-width: 0;
  flex: 1;
}

.context-tokens {
  display: flex;
  align-items: center;
  gap: 3px;
  overflow: hidden;
  white-space: nowrap;
}

.state-context-tokens {
  gap: 4px;
}

.ho-node-tag {
  flex: 0 0 auto;
  margin-left: 4px;
  padding: 1px 5px;
  border: 1px solid var(--panel-border);
  border-radius: 999px;
  background: var(--panel-soft);
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 700;
  line-height: 1.25;
}

.token-circle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  height: 12px;
  border-radius: 999px;
  flex: 0 0 auto;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
}

.token-arrow {
  color: var(--text-muted);
  font-size: 10px;
}

.mini-button {
  padding: 2px 6px;
  font-size: 11px;
  line-height: 1.2;
}

.expand-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: absolute;
  top: 5px;
  left: 5px;
  width: 10px;
  height: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  border-radius: 2px;
  font-size: 12px;
  line-height: 1;
  outline: none;
  box-shadow: none;
}

.expand-button:hover {
  background: transparent;
}

.expand-button:focus,
.expand-button:focus-visible,
.expand-button:active {
  outline: none;
  box-shadow: none;
  background: transparent;
}

.triangle-icon {
  width: 0;
  height: 0;
  border-top: 3.5px solid transparent;
  border-bottom: 3.5px solid transparent;
  border-left: 5px solid var(--text-muted);
  transition: transform 0.12s ease, border-left-color 0.12s ease;
}

.expand-button.expanded .triangle-icon {
  transform: rotate(90deg);
  border-left-color: #111827;
}

.context-detail {
  margin: 7px 0 1px 0;
  padding-top: 7px;
  border-top: 1px solid rgba(216, 224, 234, 0.8);
}

.context-bar-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.context-bar-row {
  grid-template-columns: minmax(52px, 0.75fr) 1fr 48px;
}

.context-bar-fill {
  background: #6b9fbd;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin: 4px 0 6px;
}

.summary-item {
  min-width: 0;
  padding: 3px 7px;
  border: 1px solid var(--panel-border);
  border-radius: 5px;
  background: var(--panel-soft);
}

.summary-item span {
  display: block;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.15;
}

.summary-item b {
  display: block;
  margin-top: 1px;
  color: #111827;
  font-size: 12px;
}

.scroll-block {
  overflow: auto;
  padding-right: 2px;
}

.next-step-block {
  max-height: 150px;
  flex: 0 0 auto;
}

.context-block {
  min-height: 0;
  flex: 1 1 auto;
}

.projection-block {
  max-height: 150px;
  flex: 0 0 auto;
}

.member-block {
  min-height: 0;
  flex: 1 1 auto;
}

</style>

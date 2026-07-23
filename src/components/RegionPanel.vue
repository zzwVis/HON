<!-- RegionPanel.vue -->
<script setup>
import { computed, ref, watchEffect, onMounted, nextTick } from "vue"
import { useBrushStore } from "@/store/brushStore.js"
import { usePayloadStore } from "@/store/payloadStore.js"
import { useRegionStore } from "@/store/regionStore.js"
import ForceGraph from "./ForceGraph.vue"
import {
  buildHighOrderStatesFromFirstOrder,
  buildStateKeyToClassMap,
  canonicalJsonKey,
} from "@/components/tool.js"


const props = defineProps({
  regionId: { type: String, required: true }
})

/* stores */
const brushStore = useBrushStore()
const payloadStore = usePayloadStore()
const regionStore = useRegionStore()
const showModelDialog = ref(false)
const modelDialogX = ref(0)
const modelDialogY = ref(0)
const modelInputNumber = ref(null)

/* region + brush (局部依赖) */
const region = computed(() => regionStore.regions[props.regionId])

const brush = computed(() => {
  const r = region.value
  if (!r?.brushId) return null
  return brushStore.brushes[r.brushId] || null
})

const regionTitle = computed(() => {
  const r = region.value
  if (!r) return "Region"
  return r.id === "root" ? "Region root" : `Region ${r.id}`
})

const regionSubtitle = computed(() => {
  const r = region.value
  const parts = []
  if (brush.value?.name) parts.push(brush.value.name)
  if (r?.sourceRegionId) {
    parts.push(`from ${r.sourceRegionId === "global" ? "Global" : `Region ${r.sourceRegionId}`}`)
  }
  if (r?.modelStatus === "ready") {
    const count = r.modelInfo?.num_clusters
    parts.push(count ? `local model · ${count} nodes` : "local model")
  } else if (r?.modelStatus === "running") {
    parts.push("re-aggregating")
  } else if (r?.modelStatus === "error") {
    parts.push("model failed")
  }
  return parts.join(" · ")
})

const isOverlayBase = computed(() =>
    regionStore.overlay?.baseRegionId === props.regionId
)

const isOverlayTarget = computed(() =>
    regionStore.overlay?.targetRegionId === props.regionId
)

const overlayBaseRegionId = computed(() =>
    isOverlayTarget.value ? regionStore.overlay?.baseRegionId : null
)

const overlayLabel = computed(() => {
  if (!isOverlayTarget.value || !overlayBaseRegionId.value) return ""
  return `Overlay: Region ${overlayBaseRegionId.value} on Region ${props.regionId}`
})

function isStateTransitionKey(k) {
  return String(k).includes("→")
}

function stateArrayKey(arr) {
  return (arr || []).map(v => String(v).replace(/[()']/g, "").trim()).join("→")
}

const highOrderStateKeySet = computed(() => {
  const glyph = payloadStore.payload?.glyph || {}
  const maxOrder = payloadStore.payload?.max_order || 3
  const keys = new Set()
  Object.values(glyph).forEach(g => {
    const states = Array.isArray(g?.full_order_states)
        ? g.full_order_states
        : (g?.unique_states || []).filter(st => Array.isArray(st) && st.length === maxOrder)
    states.forEach(st => keys.add(normalizeStateKey(stateArrayKey(st))))
  })
  return keys
})

function classifyStateAnchor(value) {
  const normalized = normalizeStateKey(value)
  if (highOrderStateKeySet.value.has(normalized)) return "hoState"
  return isStateTransitionKey(value) ? "firstOrderEdge" : "firstOrderNode"
}

const sliceAnchorOptions = computed(() => {
  const b = brush.value
  if (!b) return []

  const options = []
  ;(b.edges || []).forEach(edge => {
    options.push({
      id: `hoEdge:${edge}`,
      type: "hoEdge",
      value: edge,
      label: `HO Edge ${edge}`
    })
  })
  Array.from(b.classes || []).forEach(cls => {
    options.push({
      id: `hoNode:${cls}`,
      type: "hoNode",
      value: String(cls),
      label: `HO Node ${cls}`
    })
  })
  Array.from(b.states || []).forEach(state => {
    const value = String(state)
    const type = classifyStateAnchor(value)
    const labelPrefix =
        type === "hoState"
            ? "HO State"
            : (type === "firstOrderEdge" ? "First-order Edge" : "First-order Node")
    options.push({
      id: `${type}:${value}`,
      type,
      value,
      label: `${labelPrefix} ${value}`
    })
  })
  return options
})

const selectedSliceAnchor = computed(() =>
    sliceAnchorOptions.value.find(option => option.id === region.value?.sliceAnchor) || null
)

function handleDragStart(event) {
  const r = region.value
  if (!r?.applied || r.id === "root" || r.id === "global") return
  event.dataTransfer.effectAllowed = "copy"
  event.dataTransfer.setData("text/plain", r.id)
}

function handleDrop(event) {
  event.preventDefault()
  const target = region.value
  const baseId = event.dataTransfer.getData("text/plain")
  if (!target?.applied || target.id === "root" || target.id === "global") return
  if (!baseId || baseId === target.id) return

  const base = regionStore.regions[baseId]
  if (!base?.applied) return
  regionStore.setOverlay(baseId, target.id)
}

// Apply 前也提前写入 source 信息，避免 ForceGraph baseline 依赖全局 preview 时序
watchEffect(() => {
  const r = region.value
  const p = brushStore.preview?.value ?? brushStore.preview
  if (!r || !p?.sourceRid) return

  // 不覆盖已确定的来源（apply 后会写入稳定 sourceRegionId）
  if (r.sourceRegionId) return

  // 仅当该 region 绑定了当前 active brush，或尚未绑定 brush 但用户正准备 apply（activeBrush 存在且 preview 有结果）
  const activeBrushId = brushStore.activeBrushId?.value ?? brushStore.activeBrushId
  const shouldAttach =
      (r.brushId && activeBrushId && r.brushId === activeBrushId) ||
      (!r.brushId && activeBrushId && p.brushId === activeBrushId)

  if (!shouldAttach) return

  // sourceBrushId：global 视为特殊值；否则记录来源 region 当前 brushId（用于前端差分着色）
  const sourceRegion = regionStore.regions[p.sourceRid]
  const sourceBrushId = p.sourceRid === "global" ? "global" : (sourceRegion?.brushId ?? null)
  regionStore.setSourceInfo(r.id, p.sourceRid, sourceBrushId)
})


function handleSliceModeChange() {
  activateRegionPanel()
}

function activateRegionPanel() {
  const r = region.value
  if (!r?.id || regionStore.activeRegionId === r.id) return
  regionStore.setActive(r.id)
}

function apply() {
  // 不需要先点击 header 选中 target；点哪个 Apply，哪个 region 就是 target
  if (brushStore.activeBrushId) {
    regionStore.assignBrush(props.regionId, brushStore.activeBrushId)
  }

  brushStore.applyPreviewToSelectedRegion(props.regionId)   // ⭐ 真正写入这个 region
  regionStore.applyRegion(props.regionId)                   // 标记 applied


  // ⭐ 清空 source region 的高亮
  const sourceRid = brushStore.preview?.sourceRid
  if (sourceRid) {
    regionStore.setHighlightData(sourceRid, null, null)
  }
}

function openRebuildDialog(event) {
  const r = region.value
  if (!r || r.id === "root" || r.id === "global") return

  const defaultK = r.modelInfo?.num_clusters || Math.max(2, Math.min(12, Math.round(Math.sqrt(r.sequenceIds?.length || 4))))
  modelInputNumber.value = defaultK
  modelDialogX.value = event.clientX - 170
  modelDialogY.value = event.clientY + 12
  showModelDialog.value = true
}

function closeRebuildDialog() {
  showModelDialog.value = false
}

function resetLocalModel() {
  const r = region.value
  if (!r) return
  regionStore.resetRegionModel(r.id, payloadStore.payload)
  payloadStore.clearSelectionForRegion(r.id)
}

async function confirmRebuildModel() {
  const r = region.value
  if (!r || r.id === "root" || r.id === "global") return

  const nClusters = Number.parseInt(modelInputNumber.value, 10)
  if (!Number.isFinite(nClusters) || nClusters < 1) {
    window.alert("Please enter a positive integer.")
    return
  }
  if (r.sliceMode && !selectedSliceAnchor.value) {
    window.alert("Please choose a Slice Anchor first.")
    return
  }

  showModelDialog.value = false
  const rebuilt = await regionStore.rebuildRegionModel(r.id, {
    nClusters,
    refineSteps: 4,
    firstOrderSequences: r.sliceMode ? panelData.value.slicedFirstOrderSequences : null
  })
  if (rebuilt) {
    payloadStore.clearSelectionForRegion(r.id)
  }
}

/* ===== utils（原样搬过来） ===== */
// "node0 → node1","node1 → node2" → [0,1,2]
function edgesToNodeSeq(edges) {
  if (!edges || edges.length === 0) return []
  const nodes = []
  edges.forEach((e, i) => {
    const [s, t] = e.split("→").map(d => d.trim())
    const sid = parseInt(s.replace("node", ""))
    const tid = parseInt(t.replace("node", ""))
    if (i === 0) nodes.push(sid)
    nodes.push(tid)
  })
  return nodes
}

function parseEdgePairs(edgesObjOrArr) {
  const edges = Array.isArray(edgesObjOrArr)
      ? edgesObjOrArr
      : Object.values(edgesObjOrArr || {})

  return edges
      .filter(Boolean)
      .map(e => {
        const [s, t] = e.split("→").map(d => d.trim())
        const sid = parseInt(s.replace("node", ""))
        const tid = parseInt(t.replace("node", ""))
        return [sid, tid]
      })
}

function mergeWindowsIfConnected(windows) {
  if (!windows.length) return []

  // 先按原序列中的起始位置排序（重要！）
  windows.sort((a, b) => a.startIdx - b.startIdx)

  const merged = []
  let current = windows[0].seq

  for (let i = 1; i < windows.length; i++) {
    const next = windows[i].seq

    const lastOfCurrent = current[current.length - 1]
    const firstOfNext = next[0]

    if (lastOfCurrent === firstOfNext) {
      // 拼接（去掉重复的第一个元素）
      current = current.concat(next.slice(1))
    } else {
      merged.push(current)
      current = next
    }
  }

  merged.push(current)
  return merged
}

function findEdgeFirstIndices(seq, edgePairs) {
  const result = []

  for (const [a, b] of edgePairs) {
    let found = -1
    for (let i = 0; i < seq.length - 1; i++) {
      if (seq[i] === a && seq[i + 1] === b) {
        found = i
        break
      }
    }
    if (found === -1) return null
    result.push({ edge: [a, b], idx: found })
  }

  return result
}

function findEdgeAllMatches(seq, edgePair) {
  const result = []
  if (!Array.isArray(seq) || !Array.isArray(edgePair) || edgePair.length < 2) return result
  const [a, b] = edgePair
  for (let i = 0; i < seq.length - 1; i++) {
    if (seq[i] === a && seq[i + 1] === b) {
      result.push({
        idx: i,
        patternLen: 2,
        seqLen: seq.length
      })
    }
  }
  return result
}

function mergeConnectedEdges(matches) {
  // 按 idx 排序
  matches.sort((a, b) => a.idx - b.idx)

  const merged = []
  let current = {
    startIdx: matches[0].idx,
    endIdx: matches[0].idx + 1   // 覆盖两个节点
  }

  for (let i = 1; i < matches.length; i++) {
    const m = matches[i]

    // 如果是连续的
    if (m.idx === current.endIdx) {
      // 扩展当前块
      current.endIdx = m.idx + 1
    } else {
      merged.push(current)
      current = {
        startIdx: m.idx,
        endIdx: m.idx + 1
      }
    }
  }

  merged.push(current)
  return merged
}

function findSubsequenceIndex(seq, pattern) {
  if (pattern.length === 0) return -1
  for (let i = 0; i <= seq.length - pattern.length; i++) {
    let ok = true
    for (let j = 0; j < pattern.length; j++) {
      if (seq[i + j] !== pattern[j]) { ok = false; break }
    }
    if (ok) return i
  }
  return -1
}

function sliceByWindow(seq, startIdx, patternLen, prev, next) {
  const left = Math.max(0, Number(startIdx) - Number(prev))
  const right = Math.min(Number(seq.length), Number(startIdx) + Number(patternLen) + Number(next))
  return seq.slice(left, right)
}

function sliceWindowBounds(seqLen, startIdx, patternLen, prev, next) {
  const left = Math.max(0, Number(startIdx) - Number(prev))
  const right = Math.min(Number(seqLen), Number(startIdx) + Number(patternLen) + Number(next))
  return { left, right }
}

function normalizeStateKey(k) {
  return String(k).replace(/[()']/g, "").trim()
}

function sliceByClassSeq(clsSeq, classSet, prev, next) {
  if (!clsSeq) return null

  const seqSet = new Set(clsSeq.map(v => String(v)))
  const classSetStr = new Set([...classSet].map(v => String(v)))

  // 检查是否包含所有 class
  for (const c of classSetStr) {
    if (!seqSet.has(c)) {
      return null
    }
  }

  const results = []
  const prevNum = Number(prev)
  const nextNum = Number(next)
  const leftOffset = isNaN(prevNum) ? 0 : prevNum
  const rightOffset = isNaN(nextNum) ? 0 : nextNum

  // 收集所有匹配项的切片
  for (let i = 0; i < clsSeq.length; i++) {
    const currentItem = String(clsSeq[i])

    if (classSetStr.has(currentItem)) {
      const left = Math.max(0, i - leftOffset)
      const right = Math.min(clsSeq.length, i + 1 + rightOffset)

      results.push({
        slice: clsSeq.slice(left, right),
        idx: i,
        patternLen: 1,
        seqLen: clsSeq.length
      })
    }
  }

  return results.length > 0 ? results : null
}

function sliceByStateOnTokenSeq(seq, stateSet, prev, next) {
  const tokens = seq.map(x => String(x).replace(/[()']/g, "").trim())

  // ✅ 提前规范化，避免每次 some 扫描
  const normalizedStateSet = new Set([...stateSet].map(normalizeStateKey))

  for (let i = 0; i < tokens.length; i++) {
    for (let j = i + 1; j <= tokens.length; j++) {
      const subseq = tokens.slice(i, j)
      const key = subseq.join("→")
      const cleanKey = normalizeStateKey(key)

      if (normalizedStateSet.has(cleanKey)) {
        const left = Math.max(0, Number(i) - Number(prev))
        const right = Math.min(Number(tokens.length), Number(j) + Number(next))

        return {
          slice: tokens.slice(left, right),
          idx: i,
          patternLen: j - i,
          seqLen: tokens.length
        }
      }
    }
  }
  return null
}

function findStateMatchesOnTokenSeq(seq, stateKey) {
  if (!Array.isArray(seq) || !stateKey) return []
  const tokens = seq.map(x => String(x).replace(/[()']/g, "").trim())
  const normalizedTarget = normalizeStateKey(stateKey)
  const matches = []

  for (let i = 0; i < tokens.length; i++) {
    for (let j = i + 1; j <= tokens.length; j++) {
      const key = tokens.slice(i, j).join("→")
      if (normalizeStateKey(key) === normalizedTarget) {
        matches.push({
          idx: i,
          patternLen: j - i,
          seqLen: tokens.length
        })
      }
    }
  }
  return matches
}

function memberStatesForClass(classId) {
  const glyph = payloadStore.payload?.glyph?.[String(classId)]
  const maxOrder = payloadStore.payload?.max_order || 3
  return Array.isArray(glyph?.full_order_states)
      ? glyph.full_order_states
      : (glyph?.unique_states || []).filter(st => Array.isArray(st) && st.length === maxOrder)
}

function memberStateKeysForClass(classId) {
  const states = memberStatesForClass(classId)
  return new Set(states.map(st => normalizeStateKey(stateArrayKey(st))))
}

const state2posIndex = computed(() => {
  const index = new Map()
  Object.entries(payloadStore.payload?.state2pos || {}).forEach(([key, value]) => {
    index.set(canonicalJsonKey(key), value)
  })
  return index
})

function highOrderProjectionForTokenSeq(tokenSeq) {
  const maxOrder = payloadStore.payload?.max_order || 3
  const map = st2cls.value
  if (!Array.isArray(tokenSeq) || !map) return []

  return buildHighOrderStatesFromFirstOrder(tokenSeq, maxOrder)
      .map((state, endIdx) => ({
        state,
        key: normalizeStateKey(stateArrayKey(state)),
        classId: exactStateTokensToClass(state, map),
        startIdx: endIdx - state.length + 1,
        endIdx,
        length: state.length
      }))
}

function exactStateTokensToClass(stTokens, st2clsMap) {
  if (!Array.isArray(stTokens) || !st2clsMap) return null
  const key = stTokens.map(v => String(v).replace(/[()']/g, "").trim()).join("→")
  return st2clsMap.has(key) ? st2clsMap.get(key) : null
}

function findHoNodeMatchesOnTokenSeq(tokenSeq, classId, seqId = null) {
  const maxOrder = payloadStore.payload?.max_order || 3
  const memberStates = memberStatesForClass(classId)
  const statePosMatches = []

  if (seqId != null && state2posIndex.value.size > 0) {
    memberStates.forEach(state => {
      const key = canonicalJsonKey(JSON.stringify(state.map(v => String(v).replace(/[()']/g, "").trim())))
      const posMap = state2posIndex.value.get(key)
      const positions = posMap?.[String(seqId)] || []
      positions.forEach(pos => {
        const patternLen = state.length
        const idx = Number(pos) - patternLen + 1
        if (idx < 0) return
        const actualKey = normalizeStateKey(stateArrayKey(tokenSeq.slice(idx, idx + patternLen)))
        const expectedKey = normalizeStateKey(stateArrayKey(state))
        if (actualKey !== expectedKey) return
        statePosMatches.push({
          idx,
          patternLen,
          seqLen: tokenSeq.length
        })
      })
    })
  }

  if (statePosMatches.length > 0) {
    return statePosMatches
  }

  const memberKeys = memberStateKeysForClass(classId)
  if (!memberKeys.size) return []

  return highOrderProjectionForTokenSeq(tokenSeq)
      .filter(item =>
          item.length === maxOrder &&
          String(item.classId) === String(classId) &&
          memberKeys.has(item.key)
      )
      .map(item => ({
        idx: item.startIdx,
        patternLen: item.length,
        seqLen: tokenSeq.length
      }))
}

function findHoEdgeMatchesOnTokenSeq(tokenSeq, edgePair) {
  const maxOrder = payloadStore.payload?.max_order || 3
  const [sourceClass, targetClass] = edgePair || []
  if (sourceClass == null || targetClass == null) return []

  const projection = highOrderProjectionForTokenSeq(tokenSeq)
  const matches = []
  for (let i = 0; i < projection.length - 1; i++) {
    const source = projection[i]
    const target = projection[i + 1]
    if (
        source.length !== maxOrder ||
        target.length !== maxOrder ||
        String(source.classId) !== String(sourceClass) ||
        String(target.classId) !== String(targetClass)
    ) {
      continue
    }

    matches.push({
      idx: source.startIdx,
      patternLen: target.endIdx - source.startIdx + 1,
      seqLen: tokenSeq.length
    })
  }
  return matches
}

function appendFirstOrderWindow(match, tokenSeq, prev, next, sequences, slicedFirstOrderSequences) {
  const { left, right } = sliceWindowBounds(tokenSeq.length, match.idx, match.patternLen, prev, next)
  const slice = tokenSeq.slice(left, right)
  const clsSeq = firstOrderSliceToClassSeq(slice)

  if (clsSeq.length > 1) {
    sequences.push(clsSeq)
    slicedFirstOrderSequences.push([...slice])
  }
}

function firstOrderSliceToClassSeq(slice) {
  const maxOrder = payloadStore.payload?.max_order || 3
  const hoStates = buildHighOrderStatesFromFirstOrder(
      slice,
      maxOrder
  )

  const map = st2cls.value
  if (!map) return []

  return hoStates
      .filter(st => st.length === maxOrder)
      .map(st => exactStateTokensToClass(st, map))
      .filter(c => c != null)
}

/* ===== 为 states 模式预建映射（每个 panel 一次） ===== */
const st2cls = computed(() => {
  const glyph = payloadStore.payload?.glyph
  if (!glyph) return null
  return buildStateKeyToClassMap(glyph, arr => arr.join("→"))
})

/* ===== panel 局部计算结果 ===== */
const panelData = computed(() => {

  const r = region.value
  const b = brush.value

  if (r?.modelPayload) {
    const seqs = r.modelPayload.raw_sequences || []
    return {
      sequences: seqs,
      slicedFirstOrderSequences: r.modelPayload.first_order_sequences || [],
      matchedCount: seqs.length,
      prevMax: 0,
      nextMax: 0,
      brush: b,
      sliceMode: false,
      modelPayload: r.modelPayload
    }
  }

  const fullRaw = payloadStore.payload?.raw_sequences || []
  const fullTok = payloadStore.payload?.first_order_sequences || []

  if (!r.applied) {
    return {
      sequences: [],
      slicedFirstOrderSequences: [],
      prevMax: 0,
      nextMax: 0,
      brush: null,
      isPreview: false
    }
  }

  if (!b) {
    return { sequences: [], slicedFirstOrderSequences: [], prevMax: 0, nextMax: 0, brush: null, isPreview: false }
  }

  // ⭐ 使用 sequenceIds，而不是扫描所有序列
  const seqIds = r.sequenceIds ?? []

  const sequences = []
  const slicedFirstOrderSequences = []
  const matchedSequences = []
  let finalseqs = []
  let finalFirstOrder = []

  let maxPrevBound = 0
  let maxNextBound = 0
  const anchor = selectedSliceAnchor.value
  const shouldSlice = Boolean(r.sliceMode && anchor)

  for (const i of seqIds) {

    const tokenSeq = fullTok[i]
    const seq = fullRaw[i]

    if (!seq) continue
    matchedSequences.push(seq)

    if (!shouldSlice) continue
    if (!tokenSeq) continue

    if (anchor.type === "hoEdge") {
      const edgePair = parseEdgePairs([anchor.value])[0]
      const matches = findHoEdgeMatchesOnTokenSeq(tokenSeq, edgePair)
      matches.forEach(match => {
        const { idx, patternLen, seqLen } = match
        maxPrevBound = Math.max(maxPrevBound, idx)
        maxNextBound = Math.max(maxNextBound, seqLen - (idx + patternLen))
        appendFirstOrderWindow(match, tokenSeq, r.prev, r.next, sequences, slicedFirstOrderSequences)
      })
    } else if (anchor.type === "hoNode") {
      const matches = findHoNodeMatchesOnTokenSeq(tokenSeq, anchor.value, i)
      matches.forEach(match => {
        const { idx, patternLen, seqLen } = match
        maxPrevBound = Math.max(maxPrevBound, idx)
        maxNextBound = Math.max(maxNextBound, seqLen - (idx + patternLen))
        appendFirstOrderWindow(match, tokenSeq, r.prev, r.next, sequences, slicedFirstOrderSequences)
      })
    } else if (
        anchor.type === "hoState" ||
        anchor.type === "firstOrderNode" ||
        anchor.type === "firstOrderEdge"
    ) {
      const matches = findStateMatchesOnTokenSeq(tokenSeq, anchor.value)
      matches.forEach(match => {
        const { idx, patternLen, seqLen } = match
        maxPrevBound = Math.max(maxPrevBound, idx)
        maxNextBound = Math.max(maxNextBound, seqLen - (idx + patternLen))
        appendFirstOrderWindow(match, tokenSeq, r.prev, r.next, sequences, slicedFirstOrderSequences)
      })
    }
  }

  if (r.sliceMode && anchor) {
    finalseqs = sequences
    finalFirstOrder = slicedFirstOrderSequences
  } else if (r.sliceMode && !anchor) {
    finalseqs = []
    finalFirstOrder = []
  } else {
    finalseqs = matchedSequences
  }

  return {
    sequences: finalseqs,
    slicedFirstOrderSequences: finalFirstOrder,
    matchedCount: seqIds.length,
    prevMax: maxPrevBound,
    nextMax: maxNextBound,
    brush: b,
    sliceMode: r.sliceMode
  }
})


/* ✅ 把“写回 slider 上界 + clamp”放到 watchEffect（不要在 computed 里做副作用） */
function writePanelDataToRegion(r) {
  if (!r || r.modelPayload) return
  const data = panelData.value
  r.sequences = data.sequences
  r.slicedFirstOrderSequences = data.slicedFirstOrderSequences ?? []
}

watchEffect(() => {
  const r = region.value
  // if (!r) return
  if (!r || !r.applied) return  // ⭐ 只有 applied 后才自动调整

  if (r.sliceAnchor && !sliceAnchorOptions.value.some(option => option.id === r.sliceAnchor)) {
    r.sliceAnchor = null
  }

  const boundsData = panelData.value
  const { prevMax, nextMax } = boundsData

  const prevChanged = r.prevMax !== prevMax
  const nextChanged = r.nextMax !== nextMax

  r.prevMax = prevMax
  r.nextMax = nextMax

  let windowChanged = false

  // ✅ 初始化时自动拉满
  if (prevChanged && r.prev === 0 && prevMax > 0) {
    // r.prev = prevMax
    r.prev = 1
    windowChanged = true
  }

  if (nextChanged && r.next === 0 && nextMax > 0) {
    // r.next = nextMax
    r.next = 1
    windowChanged = true
  }

  // clamp（防止越界）
  if (r.prev > prevMax) {
    r.prev = prevMax
    windowChanged = true
  }
  if (r.next > nextMax) {
    r.next = nextMax
    windowChanged = true
  }

  // prev/next 刚被自动修正时，boundsData 仍然是旧窗口算出来的。
  // 下一次 Vue 更新后显式写回最新 slice，避免序列视图拿到空缓存或长度 3 的中间态。
  if (windowChanged) {
    nextTick(() => {
      if (region.value?.id === r.id) writePanelDataToRegion(r)
    })
    return
  }

  // ⭐ 写回 region（类序列 + slice 时的 first_order 供 RawSequence 用）
  writePanelDataToRegion(r)

})
</script>

<template>
  <Teleport to="body">
    <div
        v-if="showModelDialog"
        class="rebuild-dialog"
        :style="{ left: modelDialogX + 'px', top: modelDialogY + 'px' }"
        @click.stop
    >
      <div class="dialog-actions">
        <img
            src="../assets/confirm.png"
            alt="confirm"
            title="Confirm"
            @click="confirmRebuildModel"
        />
        <img
            src="../assets/delete.png"
            alt="cancel"
            title="Cancel"
            @click="closeRebuildDialog"
        />
      </div>
      <div class="dialog-label">Target HO nodes</div>
      <input
          type="number"
          min="1"
          v-model.number="modelInputNumber"
          @keydown.enter="confirmRebuildModel"
      />
    </div>
  </Teleport>

  <div
      class="panel"
      :class="{
        active: region?.id === regionStore.activeRegionId,
        'overlay-base': isOverlayBase,
        'overlay-target': isOverlayTarget
      }"
      :style="{ borderColor: brush ? brush.color : '#ccc' }"
      @dragover.prevent
      @drop="handleDrop"
  >
    <div
        class="panel-header"
        draggable="true"
        @dragstart="handleDragStart"
        @click="regionStore.setActive(region.id)"
    >
      <span v-if="brush" class="dot" :style="{ background: brush.color }" />
      <span class="title-stack">
        <span class="small-title">{{ regionTitle }}</span>
        <span v-if="regionSubtitle" class="subtitle">{{ regionSubtitle }}</span>
        <span v-if="overlayLabel" class="subtitle overlay-label">{{ overlayLabel }}</span>
      </span>

      <div class="header-scroll" @pointerdown.stop="activateRegionPanel" @click.stop>
        <div class="panel-controls" v-if="region.sliceMode && region.prevMax > 0">
          <div class="ctrl">
            <span>Prev</span>
            <input
                type="number"
                v-model.number="region.prev"
                :min="0"
                :max="region.prevMax"
                class="range-input"
                style="width: 30px !important;"
            />
          </div>
        </div>

        <div class="panel-controls" v-if="region.sliceMode && region.nextMax > 0">
          <div class="ctrl">
            <span>Next</span>
            <input
                type="number"
                v-model.number="region.next"
                :min="0"
                :max="region.nextMax"
                class="range-input"
                style="width: 30px !important;"
            />
          </div>
        </div>

        <div class="panel-controls anchor-control" v-if="region.sliceMode">
          <div class="ctrl">
            <span>Anchor</span>
            <select v-model="region.sliceAnchor" class="anchor-select">
              <option :value="null">Choose</option>
              <option
                  v-for="option in sliceAnchorOptions"
                  :key="option.id"
                  :value="option.id"
              >
                {{ option.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- 新增：将三个按钮放在一个容器里 -->
        <div class="panel-actions">
          <span class="count">
            {{ region.sliceMode ? (selectedSliceAnchor ? panelData.sequences.length + ' slices' : 'choose anchor') : panelData.matchedCount + ' seqs' }}
          </span>

          <!-- ⭐ 新增：切片模式切换复选框 -->
          <label class="slice-mode" title="Show sliced sequences">
            <input
                type="checkbox"
                v-model="region.sliceMode"
                @change="handleSliceModeChange"
            />
            <span>Slice</span>
          </label>

          <button
              v-if="isOverlayTarget"
              class="clear-overlay"
              title="Clear overlay"
              @click.stop="regionStore.clearOverlay()"
          >
            Clear
          </button>

          <button
              v-if="region.id !== 'root' && region.id !== 'global' && region.applied"
              class="model-button"
              :disabled="region.modelStatus === 'running' || !region.sequenceIds?.length"
              :title="region.modelError || 'Re-aggregate high-order network on this region'"
              @click.stop="openRebuildDialog"
          >
            {{ region.modelStatus === 'running' ? 'Running' : (region.modelStatus === 'ready' ? 'Rebuild' : 'Re-aggregate') }}
          </button>

          <button
              v-if="region.modelPayload || region.modelStatus === 'error'"
              class="model-button"
              title="Restore the pre-aggregation projection"
              @click.stop="resetLocalModel"
          >
            Reset
          </button>

          <button class="close" title="Remove region" @click.stop="regionStore.remove(region.id)">
            <img src="../assets/delete.png" alt="delete" style="width: 16px; height: 16px;">
          </button>

        </div>
      </div>
    </div>

    <ForceGraph
        v-if="panelData.sequences.length"
        :externalSequences="panelData.sequences"
        :payloadData="panelData.modelPayload"
        :regionId="region.id"
        :sourceRegionId="region.sourceRegionId"
        :overlayBaseRegionId="overlayBaseRegionId"
    />

    <div v-else class="empty">
      <div class="empty-title">Empty Region</div>
      <div class="empty-hint">Select a filter to populate</div>
    </div>
  </div>
</template>

<style scoped>
.rebuild-dialog {
  position: fixed;
  z-index: 100000;
  width: 132px;
  min-height: 54px;
  padding: 14px 12px 8px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  color: var(--text-main);
}

.dialog-actions {
  position: absolute;
  top: 6px;
  right: 7px;
  display: flex;
  gap: 5px;
}

.dialog-actions img {
  width: 15px;
  height: 15px;
  cursor: pointer;
  opacity: 0.86;
  transition: opacity 0.15s ease;
}

.dialog-actions img:hover {
  opacity: 1;
}

.dialog-label {
  margin: 8px 0 5px;
  font-size: 12px;
  font-weight: 700;
}

.rebuild-dialog input {
  width: 54px;
  height: 20px;
  padding: 0 4px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 12px;
}

/* panel */
.panel {
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  min-height: 320px;
  background: var(--panel-bg);
  overflow: hidden;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.panel-header {
  min-height: 31px;
  padding: 4px 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  background: linear-gradient(180deg, #fbfcfe, #f2f5f8);
  border-bottom: 1px solid var(--panel-border);
  color: var(--text-main);
}

.header-scroll {
  min-width: 0;
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: rgba(107, 114, 128, 0.35) transparent;
  padding: 1px 0 3px;
}

.header-scroll::-webkit-scrollbar {
  height: 5px;
}

.header-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.header-scroll::-webkit-scrollbar-thumb {
  background: rgba(107, 114, 128, 0.3);
  border-radius: 999px;
}

.header-scroll > * {
  flex: 0 0 auto;
}

/* 新增：按钮组容器 */
.panel-actions {
  display: flex;
  align-items: center;
  gap: 1px;           /* 按钮之间的间距 */
  flex: 0 0 auto;
  white-space: nowrap;
}

/* 统一按钮基础样式 */
.close, .apply, .clear-overlay, .model-button {
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  padding: 2px 3px;
  border-radius: 4px;
  transition: all 0.16s ease;
  margin-top: 0;
  color: var(--text-muted);
  line-height: 1;
}

.close:hover, .apply:hover, .clear-overlay:hover, .model-button:hover {
  background: var(--accent-soft);
  border-color: rgba(47, 111, 159, 0.25);
}

.clear-overlay {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  color: var(--accent);
}

.model-button {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  color: var(--accent);
  white-space: nowrap;
}

.model-button:disabled {
  cursor: default;
  color: var(--text-muted);
  opacity: 0.65;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.85), 0 0 0 3px rgba(36, 49, 66, 0.12);
}

.count {
  color: var(--text-muted);
  margin-top: 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.empty {
  padding: 20px;
  text-align: center;
  color: #999;
}

.ctrl {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  width: auto; /* 紧凑并排：不要固定宽度避免元素挤压/遮挡 */
}

.ctrl input[type="number"] {
  flex-shrink: 0;
}

.panel.active {
  transform: translateY(-1px);
  border-color: rgba(47, 111, 159, 0.75) !important;
  box-shadow: 0 0 0 2px rgba(47, 111, 159, 0.12), 0 10px 24px rgba(36, 49, 66, 0.12);
  z-index: 2;
}

.panel.overlay-base {
  box-shadow: inset 0 0 0 2px rgba(154, 51, 64, 0.18);
}

.panel.overlay-target {
  box-shadow: inset 0 0 0 2px rgba(47, 111, 159, 0.22), 0 10px 24px rgba(36, 49, 66, 0.12);
}

.apply {
  margin-left: 0px;
  border: none;
  background: none;
  cursor: pointer;
  margin-top: 4px;
}
.apply:hover img {
  filter: brightness(0) saturate(100%) invert(67%) sepia(61%) saturate(373%) hue-rotate(60deg) brightness(92%) contrast(89%);
}


.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: #999;
}

.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-main);
}

.small-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.title-stack {
  min-width: 54px;
  max-width: 115px;
  flex: 0 1 115px;
  display: grid;
  gap: 1px;
}

.subtitle {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overlay-label {
  color: var(--accent);
  font-weight: 700;
}

.empty-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
}
.close {
  margin-left: 0px;
  border: none;
  background: none;
  cursor: pointer;
  margin-top: 2px;
}

.close:hover img {
  filter: invert(27%) sepia(51%) saturate(2878%) hue-rotate(346deg) brightness(80%) contrast(97%);
  /* 上面的 filter 可以生成红色色调，适合删除按钮 */
}

.panel-controls {
  display: flex;
  gap: 6px;
  padding: 1px 1px;
  border-bottom: none;
  font-size: 12px;
  color: var(--text-muted);
  flex: 0 0 auto;
  white-space: nowrap;
}

.panel-controls .ctrl {
  display: flex;
  align-items: center;
  gap: 1px;
}

.range-input {
  width: 48px;
  padding: 2px 4px;
  border-radius: 4px;
  border: 1px solid var(--panel-border);
  font-size: 12px;
  color: var(--text-main);
}

.anchor-control {
  max-width: 150px;
}

.anchor-select {
  max-width: 92px;
  height: 21px;
  padding: 1px 4px;
  border: 1px solid var(--panel-border);
  border-radius: 4px;
  background: #fff;
  color: var(--text-main);
  font-size: 11px;
}

/* 切片模式切换复选框 */
.slice-mode {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  margin-left: 8px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--panel-soft);
  user-select: none;
}

.slice-mode:hover {
  background: var(--accent-soft);
}

.slice-mode input[type="checkbox"] {
  margin-top: 6px;
  cursor: pointer;
}
</style>

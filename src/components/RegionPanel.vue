<!-- RegionPanel.vue -->
<script setup>
import { computed, watchEffect, onMounted } from "vue"
import { useBrushStore } from "@/store/brushStore.js"
import { usePayloadStore } from "@/store/payloadStore.js"
import { useRegionStore } from "@/store/regionStore.js"
import ForceGraph from "./ForceGraph.vue"
import {
  buildHighOrderStatesFromFirstOrder,
  buildStateKeyToClassMap,
  stateTokensToClass
} from "@/components/tool.js"


const props = defineProps({
  regionId: { type: String, required: true }
})

/* stores */
const brushStore = useBrushStore()
const payloadStore = usePayloadStore()
const regionStore = useRegionStore()

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
  return parts.join(" · ")
})

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
  // 可选：在切换模式时执行一些操作
  console.log('Slice mode changed:', region.value.sliceMode)
  // 比如可以触发重新渲染或更新其他状态
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

  for (const i of seqIds) {

    const seq = fullRaw[i]
    const tokenSeq = fullTok[i]

    if (!seq) continue

    // ① edges 模式
    if (b.edges?.length > 0) {

      const edgePairs = parseEdgePairs(b.edges)
      const matches = findEdgeFirstIndices(seq, edgePairs)

      if (matches) {

        matchedSequences.push(seq)

        const mergedBlocks = mergeConnectedEdges(matches)

        for (const block of mergedBlocks) {

          const start = block.startIdx
          const patternLen = block.endIdx - block.startIdx + 1

          maxPrevBound = Math.max(maxPrevBound, start)
          maxNextBound = Math.max(maxNextBound, seq.length - (start + patternLen))

          const windowSeq = sliceByWindow(seq, start, patternLen, r.prev, r.next)

          sequences.push(windowSeq)
          if (tokenSeq && tokenSeq.length > 0) {
            const left = Math.max(0, Number(start) - Number(r.prev))
            const right = Math.min(tokenSeq.length, Number(start) + Number(patternLen) + Number(r.next))
            slicedFirstOrderSequences.push(tokenSeq.slice(left, right))
          }
        }
      }
    }

    // ② class 模式
    else if (b.classes && b.classes.size > 0) {

      const matches = sliceByClassSeq(seq, b.classes, r.prev, r.next)

      if (!matches) continue

      matchedSequences.push(seq)

      for (const match of matches) {

        const { slice, idx, patternLen, seqLen } = match

        maxPrevBound = Math.max(maxPrevBound, idx)
        maxNextBound = Math.max(maxNextBound, seqLen - (idx + patternLen))

        if (slice.length > 1) {
          sequences.push(slice)
          if (tokenSeq && tokenSeq.length > 0) {
            const left = Math.max(0, idx - Number(r.prev))
            const right = Math.min(tokenSeq.length, idx + 1 + Number(r.next))
            slicedFirstOrderSequences.push(tokenSeq.slice(left, right))
          }
        }
      }
    }

    // ③ states 模式
    else if (b.states && b.states.size > 0) {

      if (!tokenSeq) continue

      const match = sliceByStateOnTokenSeq(tokenSeq, b.states, r.prev, r.next)

      if (!match) continue

      matchedSequences.push(seq)

      const { slice, idx, patternLen, seqLen } = match

      maxPrevBound = Math.max(maxPrevBound, idx)
      maxNextBound = Math.max(maxNextBound, seqLen - (idx + patternLen))

      const hoStates = buildHighOrderStatesFromFirstOrder(
          slice,
          payloadStore.payload?.max_order || 3
      )

      const map = st2cls.value
      if (!map) continue

      const clsSeq = hoStates
          .map(st => stateTokensToClass(st, map, arr => arr.join("→")))
          .filter(c => c != null)

      if (clsSeq.length > 1) {
        sequences.push(clsSeq)
        slicedFirstOrderSequences.push([...slice])
      }
    }
  }

  if (r.sliceMode) {
    finalseqs = sequences
    finalFirstOrder = slicedFirstOrderSequences
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
watchEffect(() => {
  const r = region.value
  // if (!r) return
  if (!r || !r.applied) return  // ⭐ 只有 applied 后才自动调整

  const data = panelData.value

  // ⭐ 写回 region（类序列 + slice 时的 first_order 供 RawSequence 用）
  r.sequences = data.sequences
  r.slicedFirstOrderSequences = data.slicedFirstOrderSequences ?? []

  const { prevMax, nextMax } = panelData.value

  const prevChanged = r.prevMax !== prevMax
  const nextChanged = r.nextMax !== nextMax

  r.prevMax = prevMax
  r.nextMax = nextMax

  // ✅ 初始化时自动拉满
  if (prevChanged && r.prev === 0 && prevMax > 0) {
    // r.prev = prevMax
    r.prev = 1
  }

  if (nextChanged && r.next === 0 && nextMax > 0) {
    // r.next = nextMax
    r.next = 1
  }

  // clamp（防止越界）
  if (r.prev > prevMax) r.prev = prevMax
  if (r.next > nextMax) r.next = nextMax

})
</script>

<template>
  <div
      class="panel"
      :class="{ active: region?.id === regionStore.activeRegionId }"
      :style="{ borderColor: brush ? brush.color : '#ccc' }"
  >
    <div class="panel-header" @click="regionStore.setActive(region.id)">
      <span v-if="brush" class="dot" :style="{ background: brush.color }" />
      <span class="title-stack">
        <span class="small-title">{{ regionTitle }}</span>
        <span v-if="regionSubtitle" class="subtitle">{{ regionSubtitle }}</span>
      </span>

      <div class="panel-controls" v-if="region.sliceMode && region.prevMax > 0" @click.stop>
        <div class="ctrl">
          <span>Prev</span>
          <input type="range" min="0" :max="region.prevMax" v-model="region.prev" style="width: 65px !important;"/>
          <!-- ⭐ 改为可编辑数字输入，和滑动条双向绑定 -->
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

      <div class="panel-controls" v-if="region.sliceMode && region.nextMax > 0" @click.stop>
        <div class="ctrl">
          <span>Next</span>
          <input type="range" min="0" :max="region.nextMax" v-model="region.next"  style="width: 65px !important;"/>
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

      <!-- 新增：将三个按钮放在一个容器里 -->
      <div class="panel-actions">
        <span class="count">
          {{ region.sliceMode ? '' : panelData.matchedCount + ' seqs' }}
          {{ region.sliceMode ? panelData.sequences.length + ' slices' : '' }}
        </span>

        <!-- ⭐ 新增：切片模式切换复选框 -->
        <label class="slice-mode" title="Show sliced sequences" @click.stop>
          <input
              type="checkbox"
              v-model="region.sliceMode"
              @change="handleSliceModeChange"
          />
          <span>Slice</span>
        </label>

        <button class="close" title="Remove region" @click.stop="regionStore.remove(region.id)">
          <img src="../assets/delete.png" alt="delete" style="width: 16px; height: 16px;">
        </button>

      </div>
    </div>

    <ForceGraph v-if="panelData.sequences.length"  :externalSequences="panelData.sequences"
                :regionId="region.id" :sourceRegionId="region.sourceRegionId"/>

    <div v-else class="empty">
      <div class="empty-title">Empty Region</div>
      <div class="empty-hint">Select a filter to populate</div>
    </div>
  </div>
</template>

<style scoped>

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

/* 新增：按钮组容器 */
.panel-actions {
  display: flex;
  gap: 1px;           /* 按钮之间的间距 */
  margin-left: auto;   /* 关键：将整个按钮组推到右边 */
}

/* 统一按钮基础样式 */
.close, .apply {
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

.close:hover, .apply:hover {
  background: var(--accent-soft);
  border-color: rgba(47, 111, 159, 0.25);
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

.ctrl input[type="range"] {
  width: 75px !important; /* 与模板内联样式保持一致，避免被其它规则覆盖 */
  flex-shrink: 0;
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
  min-width: 0;
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
  padding: 5px 1px;
  border-bottom: 1px solid var(--panel-border);
  font-size: 12px;
  color: var(--text-muted);
}

.panel-controls .ctrl {
  display: flex;
  align-items: center;
  gap: 1px;
}

.panel-controls input[type="range"] {
  width: 80px;
}

/* 数字输入框样式，与滑动条配合使用 */
.range-input {
  width: 48px;
  padding: 2px 4px;
  border-radius: 4px;
  border: 1px solid var(--panel-border);
  font-size: 12px;
  color: var(--text-main);
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

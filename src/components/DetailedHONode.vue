<script setup>
import { ref, watch, computed } from "vue"
import * as d3 from "d3"
import { usePayloadStore } from "@/store/payloadStore"
import { useBrushStore } from "@/store/brushStore.js"

const svgRef = ref(null)
const store = usePayloadStore()
const brushStore = useBrushStore()
const searchQuery = ref("")
const searchSelectedStates = new Set()

import { useRegionStore } from "@/store/regionStore.js"

const regionStore = useRegionStore()

const activeRegion = computed(() => {
  const rid = regionStore.activeRegionId
  if (!rid) return null
  return regionStore.regions[rid]
})

const currentSourceRegion = computed(() => {
  const rid = regionStore.activeRegionId
  if (!rid || rid === "global") {
    return { id: "global", type: "global" }
  }
  return { id: rid, type: "region" }
})

const regionClasses = computed(() => {

  const r = activeRegion.value
  if (!r) return null

  const seqs = r.sequences
  if (!seqs || seqs.length === 0) return null

  const set = new Set()

  seqs.forEach(seq => {
    seq.forEach(c => {
      set.add(String(c))
    })
  })

  return set
})

/* ============================
 * watch payload
 * ============================ */
watch(
    () => store.payload,
    (data) => {
      if (data) render(data)
    },
    { immediate: true }
)

// ⭐ 监听当前选中 region 及其 sequences，当 region 切换或 finalseq 变化时重绘
watch(
    () => {
      const r = activeRegion.value
      if (!r) return null
      return {
        id: r.id,
        // 利用引用和长度变化触发；无需深比较每个元素
        seqRef: r.sequences,
        len: Array.isArray(r.sequences) ? r.sequences.length : 0,
      }
    },
    () => {
      if (store.payload) render(store.payload)
    },
    { deep: true }
)

watch(
    () => searchQuery.value,
    () => {
      if (!store.payload) return

      // 🔹 输入被清空
      if (!searchQuery.value) {
        // 只移除搜索产生的选中
        searchSelectedStates.forEach(k => {
          store.selectedStates.delete(k)
        })
        searchSelectedStates.clear()

        render(store.payload)
        return
      }

      //  有输入：执行搜索选中
      applySearchAsSelection()
      render(store.payload)
    }
)

watch(
    () => Array.from(brushStore.activeBrush?.states || []),
    () => render(store.payload)
)

// 监听选中的类的变化
watch(
    () => {
      const b = brushStore.activeBrush
      if (!b) return null
      return [
        Array.from(b.states),
        Array.from(b.classes),
        b.edges.slice()
      ]
    },
    () => {
      if (store.payload) render(store.payload)
    },
    { deep: true }
)


// 解析用户对高阶状态的搜索
function parseQuery(q) {
  if (!q) return []
  return q
      .toUpperCase()
      .split(/[,\s]+/)
      .filter(Boolean)
}

// 过滤搜索
function normalizeTokens(arr) {
  return arr.map(x => String(x).trim().toUpperCase())
}

// search ->select
function applySearchAsSelection() {
  const qTokens = parseQuery(searchQuery.value)
  if (qTokens.length === 0) return

  // 移除上一次搜索带来的选中
  searchSelectedStates.forEach(k => {
    store.selectedStates.delete(k)
  })
  searchSelectedStates.clear()

  const key = store.stateKey(qTokens)

  // ⭐ 直接把搜索串当成一个 subsequence key
  // 搜索框这里要怎么改还得想一想
  store.selectedStates.add(key)
  // 记录这是通过搜索选中的状态
  searchSelectedStates.add(key)

  // 🔹 如果 glyph 里恰好存在完全一致的 high-order-state
  //    顺便补上对应 class（用于高亮 panel）
  const { glyph } = store.payload
  Object.entries(glyph).forEach(([c, obj]) => {
    obj.unique_states.forEach(st => {
      if (store.stateKey(st) === key) {
        store.selectedClasses.add(String(c))
      }
    })
  })
}

// 用于过滤的匹配
function matchContiguous(state, queryTokens) {
  if (queryTokens.length === 0) return true
  const s = normalizeTokens(state)
  const q = normalizeTokens(queryTokens)

  // 连续子串匹配：q 必须出现在 s 的某个连续片段中
  for (let i = 0; i <= s.length - q.length; i++) {
    let ok = true
    for (let j = 0; j < q.length; j++) {
      if (s[i + j] !== q[j]) { ok = false; break }
    }
    if (ok) return true
  }
  return false
}

// 搜索框：既要支持「连续几个 token 全词匹配」，也要支持「关键词按先后顺序出现在整条状态里」
// （含同一 token 内子串，如 Attempt(Miss) 里先后出现 ATTEMPT、MISS）
function matchStateSearch(state, queryTokens) {
  if (!queryTokens || queryTokens.length === 0) return true
  if (!Array.isArray(state) || state.length === 0) return false

  if (matchContiguous(state, queryTokens)) return true

  const s = normalizeTokens(state)
  const haystack = s.join(" ")
  const q = normalizeTokens(queryTokens)
  let pos = 0
  for (const part of q) {
    if (!part) continue
    const idx = haystack.indexOf(part, pos)
    if (idx === -1) return false
    pos = idx + part.length
  }
  return true
}

// 用于选中状态的匹配
function matchExact(state, queryTokens) {
  if (queryTokens.length === 0) return false

  // 注意：这里最好用你已经写好的清洗逻辑，避免 ('A' 这种情况
  const s = normalizeTokens(normalizeState(state))
  const q = normalizeTokens(queryTokens)

  if (s.length !== q.length) return false
  for (let i = 0; i < q.length; i++) {
    if (s[i] !== q[i]) return false
  }
  return true
}

function normalizeState(st) {
  if (!Array.isArray(st)) return st

  return st.map(s =>
      String(s)
          .replace(/[()']/g, "")
          .trim()
  )
}

/* ============================
 * main render
 * ============================ */
function render(data) {
  let cursorX = 0
  let cursorY = 0
  let usedMaxWidth = 0

  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const { glyph } = data
  const color = store.colorScale

  let classes = Object.keys(glyph)

  const rset = regionClasses.value

  if (rset && rset.size > 0) {
    classes = classes.filter(c => rset.has(String(c)))
  }

  // ① 全局最长 high-order-state 长度
  const maxLenGlobal = d3.max(classes, c =>
      d3.max(glyph[c].raw_states, st => st.length) || 1
  ) || 1

  /* ---- layout ---- */
  const minPanelW = 145
  const panelH = 200
  // 控制一行有几个面板
  const panelsPerRow = 2
  const gapX = 10
  const gapY = 16

  const r = 7
  const xGap = 22
  const yGap = 22

  const root = svg.append("g")
      .attr("transform", "translate(8,8)")

  const queryTokens = parseQuery(searchQuery.value)

  classes.forEach((c, idx) => {
    // ⭐ 类的高亮只由 brush.classes 决定，不再从 states 推导
    const activeBrush = brushStore.activeBrush
    const strokeColor =
        activeBrush && activeBrush.classes.has(String(c))
            ? activeBrush.color
            : "#ccc"

    const filteredStates = glyph[c].unique_states.filter(st => {
      if (queryTokens.length === 0) return true
      return matchStateSearch(st, queryTokens)
    })
    // const filteredStates = glyph[c].unique_states

    if (filteredStates.length === 0) return

    const panelW = Math.max(minPanelW, maxLenGlobal * xGap + 40)
    const maxRowWidth = panelsPerRow * panelW + (panelsPerRow - 1) * gapX

    if (cursorX + panelW > maxRowWidth) {
      cursorX = 0
      cursorY += panelH + gapY
    }

    const gx = cursorX
    const gy = cursorY
    cursorX += panelW + gapX
    usedMaxWidth = Math.max(usedMaxWidth, cursorX)

    const panel = root.append("g")
        .attr("transform", `translate(${gx},${gy})`)

    /* ---- border ---- */
    panel.append("rect")
        .attr("width", panelW)
        .attr("height", panelH)
        .attr("rx", 10)
        .attr("fill", "#fafafa")
        .attr("stroke", strokeColor)
        // .attr("stroke", isClassSel ? brushColor : "#ccc")
        .style("cursor", "pointer")
        .on("click", (event) => {
          event.stopPropagation()
          if (!brushStore.canEditActiveBrushFromRegion(currentSourceRegion.value.id)) return

          // brushStore.setActivePanelRegion("global", "global")
          brushStore.setActivePanelRegion(
              currentSourceRegion.value.id,
              currentSourceRegion.value.type
          )
          brushStore.toggleClass(String(c))
        })


    // 防止子元素挡住panel点击
    panel.style("pointer-events", "all")

    /* ---- title ---- */
    panel.append("text")
        .attr("x", 10)
        .attr("y", 16)
        .style("font-size", "15px")
        .style("font-weight", "600")
        .text(`node ${c}`)

    drawStatesPanel(
        panel,
        filteredStates,
        color,
        r,
        xGap,
        yGap,
        panelW,
        panelH,
        c
    )
  })

  // ✅ 最终设置 SVG 尺寸
  svg.attr("width", usedMaxWidth)
  svg.attr("height", cursorY + panelH + 20)
}

/* ============================
 * draw states inside panel
 * ============================ */
function drawStatesPanel(
    panel,
    states,
    color,
    r,
    xGap,
    yGap,
    panelW,
    panelH,
    c
) {
  const viewW = panelW - 20
  const viewH = panelH - 20

  const maxLenPanel = d3.max(states, st => st.length) || 1

  // foreignObject
  const fo = panel.append("foreignObject")
      .attr("x", 10)
      .attr("y", 30)
      .attr("width", viewW)
      .attr("height", viewH)

  const div = fo.append("xhtml:div")
      .style("width", "100%")
      .style("height", "90%")
      .style("overflow", "auto")
      .style("overflow-y", "auto")  // 只允许垂直滚动
      .style("overflow-x", "hidden")  // 禁止水平滚动

  // inner svg
  const innerSvg = div.append("svg")
      .attr("width", viewW)
      .attr("height", states.length * yGap + 20)

  const g = innerSvg.append("g")
      .attr("transform", "translate(10,10)")

  states.forEach((rawSt, rowIdx) => {
    // ✅ 1) stKey 仍然基于原始 rawSt（不破坏 toggleState 的一致性）
    const stKey = store.stateKey(rawSt)
    const activeBrush = brushStore.activeBrush
    // const isSel = brushStore.activeBrush?.states.has(stKey)


    // ✅ 2) 绘制标签/布局用去掉括号引号的短串；颜色必须用与 legend / colorScale.domain 一致的原始 token
    const stTokensRaw = Array.isArray(rawSt)
        ? rawSt.map(s => String(s).trim())
        : []
    const stTokens = stTokensRaw.map(s => s.replace(/[()']/g, "").trim())

    const y = rowIdx * yGap

    // ✅ 3) 绘制/布局用 stTokens；填色用 stTokensRaw（避免 Attempt(Miss) → AttemptMiss 与全局 colormap 对不上）
    const contentW = (stTokens.length - 1) * xGap
    const maxContentW = (maxLenPanel - 1) * xGap
    const offsetX = maxContentW - contentW + 4

    const brushColor = activeBrush?.color || "#787878"

    const hitBrushes = Object.values(brushStore.brushes)
        .filter(b => b.states.has(stKey))

    const activeHit = activeBrush && activeBrush.states.has(stKey)

    const strokeColor = hitBrushes.length
        ? hitBrushes[0].color
        : "transparent"

    g.append("rect")
        .attr("x", offsetX - r - 6)
        .attr("y", y - yGap/2 + 2)
        .attr("width", contentW + r*2 + 12)
        .attr("height", yGap - 4)
        .attr("rx", 6)
        .attr("fill", "transparent")
        .attr("stroke", strokeColor)
        .attr("stroke-width", activeHit ? 1.5 : 1)
        .style("cursor", "pointer")
        .on("click", (event) => {
          event.stopPropagation()
          if (!brushStore.canEditActiveBrushFromRegion(currentSourceRegion.value.id)) return

          // brushStore.setActivePanelRegion("global", "global")
          brushStore.setActivePanelRegion(
              currentSourceRegion.value.id,
              currentSourceRegion.value.type
          )
          brushStore.toggleState(stKey, c)
        })

    // g.append("rect")
    //     .attr("x", offsetX - r - 6)
    //     .attr("y", y - yGap/2 + 2)
    //     .attr("width", contentW + r*2 + 12)
    //     .attr("height", yGap - 4)
    //     .attr("rx", 6)
    //     .attr("fill", "transparent")
    //     .attr("stroke", isSel ? brushColor : "transparent")
    //     .style("cursor", "pointer")
    //     .on("click", (event) => {
    //       event.stopPropagation()
    //       brushStore.toggleState(stKey, c)
    //     })

    for (let i = 0; i < stTokens.length - 1; i++) {
      g.append("line")
          .attr("x1", i * xGap + offsetX)
          .attr("y1", y)
          .attr("x2", (i + 1) * xGap + offsetX)
          .attr("y2", y)
          .attr("stroke", "#aaa")
          .style("pointer-events", "none")
    }

    stTokens.forEach((_, i) => {
      const key = stTokensRaw[i] ?? ""
      const fill = typeof color === "function" ? color(key) : "#999"
      g.append("circle")
          .attr("cx", i * xGap + offsetX)
          .attr("cy", y)
          .attr("r", r)
          .attr("fill", fill ?? "#999")
          .style("pointer-events", "none")
    })
  })

}
</script>

<template>
  <div class="wrap">
    <div class="global-header">
      <span>Higher order state → Node Mapping</span>
    </div>

    <div class="toolbar">
      <input
          v-model="searchQuery"
          placeholder="Search state"
          class="search-input"
      />
    </div>

    <div class="chart-container">
      <svg ref="svgRef"></svg>
    </div>
  </div>
</template>

<style scoped>
.wrap {
  width: 100%;
  top: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--panel-bg);
}

.chart-container {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 6px 2px 8px 4px;
}

/* 关键：让表头固定在顶部 */
.global-header {
  position: sticky;
  top: 0;
  z-index: 100;
  padding: 8px 9px;
  background: linear-gradient(180deg, #fbfcfe, #f2f5f8);
  border-bottom: 1px solid var(--panel-border);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-main);
  letter-spacing: 0.01em;
}

svg {
  display: block;
  background: transparent;
}

.toolbar {
  padding: 8px;
  border-bottom: 1px solid #edf1f5;
}

.search-input {
  width: 100%;
  padding: 5px 8px;
  border-radius: 5px;
  border: 1px solid var(--panel-border);
  font-size: 12px;
  color: var(--text-main);
  background: var(--panel-soft);
}

.search-input:focus {
  outline: 2px solid rgba(47, 111, 159, 0.18);
  border-color: rgba(47, 111, 159, 0.65);
  background: #fff;
}
</style>

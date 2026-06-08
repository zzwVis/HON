<script setup>
import { ref, watch } from "vue"
import * as d3 from "d3"
import {
  computeLayerMap, curvedTaperedLinkPath, canonicalJsonKey, computeMaxWindowRangeFirstOrder, sliceSequencesFirstOrder,
  buildHighOrderStatesFromFirstOrder, buildStateKeyToClassMap, stateTokensToClass,
  selfLoopTaperedPath
} from "./tool.js"
import { usePayloadStore } from "@/store/payloadStore.js"
import { storeToRefs } from "pinia"
import { edgeKey } from "@/components/brush.js";
import { useBrushStore } from "@/store/brushStore.js"

/* ===============================
 * refs & store
 * =============================== */
const svgRef = ref(null)
const linkSelRef = ref(null) // 可选
const payloadStore = usePayloadStore()
const tooltipRef = ref(null)
const { prevSteps, nextSteps, windowMode } = storeToRefs(payloadStore)
const maxPrevSteps = ref(0)
const maxNextSteps = ref(0)
const brushStore = useBrushStore()
const linkGrayRef = ref(null)

function showTooltip(html, event) {
  const el = d3.select(tooltipRef.value)
  el.html(html)
      .style("left", event.offsetX + 12 + "px")
      .style("top", event.offsetY + 12 + "px")
      .style("opacity", 1)
}

function hideTooltip() {
  d3.select(tooltipRef.value).style("opacity", 0)
}

/* ===============================
 * watch filtered payload
 * =============================== */
watch(
    () => [
      payloadStore.filteredPayload,
      prevSteps.value,
      nextSteps.value,
      windowMode.value
    ],
    ([data]) => {
      const svg = d3.select(svgRef.value)
      svg.selectAll("*").remove()
      if (!data) return
      renderGraph(data)
    },
    { immediate: true }
)

// 更新slider
watch(
    () => [maxPrevSteps.value, maxNextSteps.value],
    ([pMax, nMax], [oldPMax, oldNMax]) => {

      // prev
      if (
          prevSteps.value == null ||
          prevSteps.value === oldPMax
      ) {
        prevSteps.value = pMax
      }

      // next
      if (
          nextSteps.value == null ||
          nextSteps.value === oldNMax
      ) {
        nextSteps.value = nMax
      }
    }
)

watch(
    () => payloadStore.selectedStates,
    (s) => {
      if (!s || s.size === 0) {
        prevSteps.value = null
        nextSteps.value = null
      }
    }
)

// 监听画笔的切换事件
watch(
    () => brushStore.activeBrushId,
    () => updateEdgeBrushStyles()
)

watch(
    () => brushStore.brushes,
    () => updateEdgeBrushStyles(),
    { deep:true }
)


// 根据选择的画笔更新边的颜色
function updateEdgeBrushStyles() {

  const linkSel = linkSelRef.value
  const linkGray = linkGrayRef.value
  if (!linkSel || !linkGray) return

  linkSel
      .attr("fill", d => {
        const sid = d.source
        const tid = d.target
        const key = edgeKey(d)

        // 找到该边属于哪个画笔
        for (const b of Object.values(brushStore.brushes)) {
          if (b.edges.includes(key)) {

            // 普通边：上色
            if (sid !== tid) return b.color
          }
        }

        // 默认普通边灰色
        return sid !== tid ? linkGray(d.value) : "none"
      })

      .attr("stroke", d => {

        const sid = d.source
        const tid = d.target
        const key = edgeKey(d)

        for (const b of Object.values(brushStore.brushes)) {
          if (b.edges.includes(key)) {

            // 自环：上色
            if (sid === tid) return b.color
          }
        }

        // 默认自环灰色
        return sid === tid ? linkGray(d.value) : "none"
      })
}

/* ===============================
 * main render
 * =============================== */
function buildGraphFromSequences(seqs) {

  const nodeMap = new Map()
  const nodes = []
  const linkCounter = new Map()

  function getNode(c) {
    const id = `node${c}`
    if (!nodeMap.has(id)) {
      nodeMap.set(id, true)
      nodes.push({ id, class: c })
    }
    return id
  }

  seqs.forEach(seq => {
    for (let i = 0; i < seq.length - 1; i++) {
      const c1 = seq[i]
      const c2 = seq[i + 1]

      const s = getNode(c1)
      const t = getNode(c2)

      const key = `${s}->${t}`
      linkCounter.set(key, (linkCounter.get(key) || 0) + 1)
    }
  })

  const links = Array.from(linkCounter.entries()).map(
      ([k, v]) => {
        const [s, t] = k.split("->")
        return { source: s, target: t, value: v }
      }
  )

  return { nodes, links }
}

function renderGraph(data) {
  // 建立 state -> class 的映射
  const state2posIndex = new Map()
  Object.entries(data.state2pos || {}).forEach(([k, v]) => {
    state2posIndex.set(canonicalJsonKey(k), v)
  })

  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const { glyph, legend } = data
  if (!data.raw_sequences) return

  // filtered 之后的序列（来自 filteredPayload） 已经在原始的全部序列中的下标
  const filteredSeqs = data.raw_sequences
  const filteredSeqIds = data.sequence_ids
  const filteredSeqId2Index = new Map()
  filteredSeqIds.forEach((sid, i) => {
    filteredSeqId2Index.set(String(sid), i)
  })

  const { maxPrev, maxNext } =
      computeMaxWindowRangeFirstOrder(
          data.first_order_sequences,
          payloadStore.selectedStates
      )

  maxPrevSteps.value = Number(maxPrev)
  maxNextSteps.value = Number(maxNext)

  // 如果是第一次 or 超出范围，则重置
  if (prevSteps.value > maxPrev) prevSteps.value = maxPrev
  if (nextSteps.value > maxNext) nextSteps.value = maxNext

  // ⭐ 初始自动铺满窗口
  if (prevSteps.value == null)
    prevSteps.value = maxPrev

  if (nextSteps.value == null)
    nextSteps.value = maxNext

  // 1) 一阶窗口序列（token）
  const slicedFirstSeqs =
      sliceSequencesFirstOrder(
          data.first_order_sequences,          // 一阶 token 序列
          payloadStore.selectedStates,
          prevSteps.value,
          nextSteps.value,
          windowMode.value
      )

  // 2) 准备 stateKeyClean（必须和 store 里一致：去括号/引号/trim）
  const stateKeyClean = (arr) =>
      arr.map(x => String(x).replace(/[()']/g, "").trim()).join("→")

  // 3) 建 stateKey -> class 映射（从 glyph 的 unique_states 来）
  const st2cls = buildStateKeyToClassMap(data.glyph, stateKeyClean)

 // 4) slicedFirstSeqs → 高阶状态序列 → 类序列
  const maxOrder = Number(data.max_order || 3)

  const classSeqs = slicedFirstSeqs.map(seq => {
    const cleanSeq = seq.map(x => String(x).replace(/[()']/g, "").trim())
    const hoStates = buildHighOrderStatesFromFirstOrder(cleanSeq, maxOrder)

    // 每个高阶状态映射到类（回退找）
    const clsSeq = hoStates
        .map(st => stateTokensToClass(st, st2cls, stateKeyClean))
        .filter(x => x != null)

    return clsSeq
  })

  payloadStore._classSeqs = classSeqs

  console.log("类序列",classSeqs)

  // 5) 用“类序列”建图
  const graph = buildGraphFromSequences(classSeqs)


  const placeholder = legend.placeholder
  const tokens = legend.tokens.filter(t => t !== placeholder)

  // const color = buildColorScale(tokens)
  payloadStore.buildGlobalColorScale(tokens)
  const color = payloadStore.colorScale

  const rect = svgRef.value.getBoundingClientRect()
  const width = rect.width
  const height = rect.height

  /* ---------- zoom ---------- */
  const root = svg.append("g")

  const zoom = d3.zoom()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => {
        root.attr("transform", event.transform)
      })

  svg.call(zoom)

  svg.call(
      zoom.transform,
      d3.zoomIdentity
          .translate(width / 4, height / 4)
          .scale(0.5)
  )

  /* ---------- arrow ---------- */
  const defs = svg.append("defs")

  defs.append("marker")
      .attr("id", "arrow-sub")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 28)
      .attr("refY", 0)
      .attr("markerWidth", 3)
      .attr("markerHeight", 3)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4 L9,0 L0,4 Z")
      .attr("fill", "#666")

  /* ---------- clone data ---------- */
  const nodes = graph.nodes.map(d => ({ ...d }))
  const links = graph.links.map(d => ({ ...d }))

  /* ===============================
   * entropy per node
   * =============================== */
  const outMap = new Map()
  const inMap = new Map()

  links.forEach(l => {
    const sid = typeof l.source === "object" ? l.source.id : l.source
    if (!outMap.has(sid)) outMap.set(sid, [])
    outMap.get(sid).push(l)
  })

  nodes.forEach(n => {
    const outLs = outMap.get(n.id) || []
    const inLs  = inMap.get(n.id)  || []

    n.outFlow = d3.sum(outLs, d => d.value)
    n.inFlow  = d3.sum(inLs,  d => d.value)
    n.entropy = entropyFromLinks( outLs)
  })

  const maxEntropy = d3.max(nodes, d => d.entropy) || 1

  links.forEach(l => {
    const tid = typeof l.target === "object" ? l.target.id : l.target
    if (!inMap.has(tid)) inMap.set(tid, [])
    inMap.get(tid).push(l)
  })

  const entropyColor = d3.scaleLinear()
      .domain([0, maxEntropy])
      .range(["#2166ac", "#f7f7f7"])


  const values = links
      .map(d => Number(d.value))
      .filter(v => !Number.isNaN(v))

  const extent = d3.extent(values)

  /* ---------- links ---------- */
  const linkGray = d3.scaleLinear()
      .domain(d3.extent(links, d => d.value))
      .range(["#dddddd", "#444444"])

  linkGrayRef.value = linkGray

  const linkSel = root.append("g")
      .attr("class", "link-layer")
      .selectAll("path")
      .data(links)
      .enter()
      .append("path")
      .attr("fill", d => {
        const sid = d.source
        const tid = d.target
        return sid === tid ? "none" : linkGray(d.value)
      })
      .attr("stroke", d => {
        const sid = d.source
        const tid = d.target
        return sid === tid ? linkGray(d.value) : "none"
      })
      .attr("stroke-width", d => {
        const sid = d.source
        const tid = d.target
        return sid === tid ? 8 : 0
      })
      .attr("stroke-linecap", "round")
      .attr("opacity", 0.9)

  linkSel
      .on("mouseenter", function(event, d) {
        showTooltip(
            `
      ${d.source.class} → ${d.target.class}<br/>
      value: ${d.value}
      `,
            event
        )
      })
      .on("mouseleave", hideTooltip)
      .on("click", (event, d) => {
        event.stopPropagation()
        if (!brushStore.activeBrushId) return

        const key = edgeKey(d)

        brushStore.toggleEdge(
            brushStore.activeBrushId,
            key
        )

        updateEdgeBrushStyles()
      })

  linkSelRef.value = linkSel

  /* ---------- nodes ---------- */
  const nodeSel = root.append("g")
      .selectAll("g")
      .data(nodes)
      .enter()
      .append("g")
      .call(
          d3.drag()
              .on("start", dragstarted)
              .on("drag", dragged)
              .on("end", dragended)
      )

  nodeSel
      .on("mouseenter", function(event, d) {

        linkSel.attr("opacity", l =>
            l.source.id === d.id || l.target.id === d.id ? 1 : 0.05
        )

        const outDeg = outMap.get(d.id)?.length || 0
        const inDeg  = inMap.get(d.id)?.length || 0

        showTooltip(
            `
      class: ${d.class}<br/>
      entropy: ${d.entropy.toFixed(3)}<br/>
      out-flow: ${d.outFlow}<br/>
      in-flow: ${d.inFlow}
      `,
            event
        )
      })
      .on("mouseleave", function() {
        linkSel.attr("opacity", 0.85)
        hideTooltip()
      })

  const NODE_W = 140
  const NODE_H = 64

  nodeSel.append("rect")
      .attr("x", -NODE_W/2)
      .attr("y", -NODE_H/2)
      .attr("width", NODE_W)
      .attr("height", NODE_H)
      .attr("rx", 10)
      .attr("fill", "#f5f5f5")
      .attr("stroke", d => entropyColor(d.entropy))
      .attr("stroke-width", 2)

  nodeSel.append("text")
      .attr("x", -NODE_W/2 - 6)
      .attr("y", 0)
      .attr("text-anchor", "end")
      .attr("dominant-baseline", "middle")
      .style("font-size", "20px")
      .text(d => `${d.class}`)


  /* ---------- glyph ---------- */
  drawGlyphForce(nodeSel, glyph, tokens, color, NODE_W, NODE_H)

  /* ===============================
   * layout
   * =============================== */
  const layerMap = computeLayerMap(data.raw_sequences)
  const maxLayer = d3.max(nodes, d => layerMap.get(String(d.class)) ?? 0) || 1

  const xScale = d3.scaleLinear()
      .domain([0, maxLayer])
      .range([40, width - 40])

  nodes.forEach(n => {
    const L = layerMap.get(String(n.class)) ?? 0
    n.x = xScale(L) + (Math.random() - 0.5) * 40
    n.y = height/2 + (Math.random() - 0.5) * 80
  })

  const outDegrees = nodes.map(
      d => outMap.get(d.id)?.length || 0
  )

  const outScale = d3.scaleLinear()
      .domain(d3.extent(outDegrees))
      .range([0.8, 1.8])   // 0.8-1.8出度低的紧凑

  const rScale = d3.scaleLinear()
      .domain(d3.extent(outDegrees))
      .range([300, 60])   // 低出度 → 外圈；高出度 → 中心

  const degPairs = links.map(d => {
    const ds = outMap.get(d.source)?.length || 0
    const dt = outMap.get(d.target)?.length || 0
    return Math.abs(ds - dt)
  })

  const diffScale = d3.scaleLinear()
      .domain(d3.extent(degPairs))
      .range([0.6, 1.6])   // 小差异 → 大倍率；大差异 → 小倍率

  const sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links)
          .id(d => d.id)
          // .distance(d => {
          //   const c1 = layerMap.get(String(d.source.class)) ?? 0
          //   const c2 = layerMap.get(String(d.target.class)) ?? 0
          //   return c2 > c1 ? 200 : 320   // 回流边更长
          // })
          .strength(d => {
            const c1 = layerMap.get(String(d.source.class)) ?? 0
            const c2 = layerMap.get(String(d.target.class)) ?? 0
            return c2 > c1 ? 0.3 : 0.08
          })
          .distance(d => {
            const ds = outMap.get(d.source.id)?.length || 0
            const dt = outMap.get(d.target.id)?.length || 0
            const diff = Math.abs(ds - dt)

            const base = 260
            return base / diffScale(diff)
          })
      )

      .force("charge", d3.forceManyBody().strength(-800))
      .force("center", d3.forceCenter(width / 2, height / 2))
      // .force("collide", d3.forceCollide().radius(Math.max(NODE_W, NODE_H)))
      .force("radial", d3.forceRadial(
          d => rScale(outMap.get(d.id)?.length || 0),
          width / 2,
          height / 2
      ).strength(0.4))

      .force("collide", d3.forceCollide()
          .radius(d => {
            // 出边多的紧凑
            const outDeg = outMap.get(d.id)?.length || 0
            return Math.max(NODE_W, NODE_H) * outScale(outDeg)
          })
      )

  sim.on("tick", () => {
    linkSel.attr("d", d => {
      const sid = d.source.id
      const tid = d.target.id

      if (sid === tid) {
        return selfLoopTaperedPath(d, NODE_W, NODE_H)      // ✅ 新自环
      }
      return curvedTaperedLinkPath(d, 10, 1)
    })

    nodeSel.attr("transform", d => `translate(${d.x},${d.y})`)
  })

  function dragstarted(event, d) {
    if (!event.active) sim.alphaTarget(0.3).restart()
    d.fx = d.x
    d.fy = d.y
  }

  function dragged(event, d) {
    d.fx = event.x
    d.fy = event.y
  }

  function dragended(event, d) {
    if (!event.active) sim.alphaTarget(0)
    d.fx = null
    d.fy = null
  }
}

/* ===============================
 * utilities
 * =============================== */

function buildColorScale(tokens) {
  const palette = [
    ...d3.schemeTableau10,
    ...(d3.schemeSet3 || []),
    ...(d3.schemePaired || [])
  ]

  return d3.scaleOrdinal()
      .domain(tokens)
      .range(tokens.map((_, i) => palette[i % palette.length]))
}

function entropyFromLinks(ls) {
  if (!ls || ls.length === 0) return 0
  const sum = d3.sum(ls, d => d.value)
  if (sum === 0) return 0

  let H = 0
  ls.forEach(d => {
    const p = d.value / sum
    if (p > 0) H -= p * Math.log(p)
  })
  return H
}

/* ===== 直接从你主文件拷贝 drawGlyphForce ===== */
import { drawGlyphForce } from "./drawGlyphForce.js"
</script>

<template>
  <div class="sub-force-container">
    <div class="window-control">
      <div>
        Prev:
        <input
            v-if="maxPrevSteps > 0 && prevSteps !== null"
            :key="`prev-${maxPrevSteps}`"
            type="range"
            min="0"
            :max="maxPrevSteps"
            v-model.number="prevSteps"
        />
        {{ prevSteps }}
      </div>

      <div>
        Next:
        <input
            v-if="maxNextSteps > 0 && nextSteps !== null"
            :key="`next-${maxNextSteps}`"
            type="range"
            min="0"
            :max="maxNextSteps"
            v-model.number="nextSteps"
        />
        {{ nextSteps }}
      </div>

      <select v-model="windowMode">
        <option value="union">Union</option>
        <option value="split">Split</option>
      </select>

    </div>

    <div class="sub-force-wrapper">
      <svg ref="svgRef"></svg>
      <div ref="tooltipRef" class="tooltip"></div>
    </div>
  </div>
</template>


<style scoped>
.sub-force-wrapper {
  width: 100%;
  height: 100%;
  position: relative; /* 关键：tooltip 定位一致 */
}

svg {
  width: 100%;
  height: 100%;
  background: #ffffff;
  border: 1px solid #ddd;
  border-radius: 4px;
}

.tooltip {
  position: absolute;
  pointer-events: none;
  background: rgba(0, 0, 0, 0.75);
  color: #fff;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.2;
  opacity: 0;
  transition: opacity 0.15s ease;
  white-space: nowrap;
  text-align: left;
  z-index: 1000;
}
.window-control {
  display: flex;
  gap: 16px;
  padding: 6px 10px;
  font-size: 12px;
  align-items: center;
}

.sub-force-wrapper {
  flex: 1;          /* ⭐ 吃掉剩余高度 */
  width: 100%;
  position: relative;
}

</style>

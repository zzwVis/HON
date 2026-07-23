<script setup>
import { ref, watch, onMounted } from "vue"
import * as d3 from "d3"
import {entropyFromLinks} from "./tool.js";
import { useRegionStore } from "@/store/regionStore.js"  // ⭐ 新增

import {
  applyLayeredLayout,
  computeLayerMap,
  selfLoopTaperedPath,
  curvedTaperedLinkPath
} from "./tool.js"

import { usePayloadStore } from "@/store/payloadStore.js"
import { useBrushStore } from "@/store/brushStore.js"
import { drawGlyphForce } from "./drawGlyphForce.js"
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";

/* ===============================
 * props
 * =============================== */

const props = defineProps({
  externalSequences: Array,
  payloadData: Object,
  regionId: String,
  sourceRegionId: String,   // ⭐ 新增
  overlayBaseRegionId: String,
})

/* ===============================
 * refs
 * =============================== */

const svgRef = ref(null)
const nodeSelRef = ref(null)
const linkSelRef = ref(null)
const linkLineSelRef = ref(null)
const tooltipRef = ref(null)
const noVisibleNodes = ref(false)
// ⭐ 新增这一行
const updateHighlightStylesFn = ref(null)

const payloadStore = usePayloadStore()
const brushStore = useBrushStore()
const regionStore = useRegionStore()  // ⭐ 新增

/* ===============================
 * helpers
 * =============================== */

function edgeKey(d) {
  return `${d.source.id}→${d.target.id}`
}

function toGraphNodeId(v) {
  if (v == null) return null
  const s = String(v)
  return s.startsWith("node") ? s : `node${s}`
}

function shortList(list, n = 8) {
  return Array.isArray(list) ? list.slice(0, n) : []
}

function showTooltip(html, event) {
  const el = d3.select(tooltipRef.value)
  el.html(html)
      .style("left", event.clientX + 12 + "px")
      .style("top", event.clientY + 12 + "px")
      .style("opacity", 1)
}

function hideTooltip() {
  d3.select(tooltipRef.value).style("opacity", 0)
}

function currentPayloadData() {
  return props.payloadData || payloadStore.payload
}

function resolveNodeOverlaps(nodes, nodeW, nodeH, padX = 8, padY = 6, iterations = 80) {
  if (!Array.isArray(nodes) || nodes.length < 2) return

  const halfW = nodeW / 2
  const halfH = nodeH / 2
  for (let it = 0; it < iterations; it++) {
    let moved = false
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]
        const b = nodes[j]
        let dx = b.x - a.x
        let dy = b.y - a.y
        if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
          const angle = ((i * 928371 + j * 364479) % 360) * Math.PI / 180
          dx = Math.cos(angle) * 0.01
          dy = Math.sin(angle) * 0.01
        }
        const minDx = halfW * 2 + padX
        const minDy = halfH * 2 + padY
        const overlapX = minDx - Math.abs(dx)
        const overlapY = minDy - Math.abs(dy)
        if (overlapX <= 0 || overlapY <= 0) continue

        if (overlapX < overlapY) {
          const sign = dx >= 0 ? 1 : -1
          const push = overlapX / 2 + 0.1
          a.x -= sign * push
          b.x += sign * push
        } else {
          const sign = dy >= 0 ? 1 : -1
          const push = overlapY / 2 + 0.1
          a.y -= sign * push
          b.y += sign * push
        }
        moved = true
      }
    }
    if (!moved) break
  }
}

/* ===============================
 * 边频缓存：仅高亮/差分需要；preview/sourceRegion 变化时只刷新样式，不重跑 FA2
 * =============================== */
function buildEdgeCountFromSeqs(seqs) {
  const m = new Map()
  if (!Array.isArray(seqs)) return m
  for (const seq of seqs) {
    if (!Array.isArray(seq) || seq.length < 2) continue
    for (let i = 0; i < seq.length - 1; i++) {
      const s = seq[i]
      const t = seq[i + 1]
      const k = `node${s}→node${t}`
      m.set(k, (m.get(k) || 0) + 1)
    }
  }
  return m
}

function buildNodeCountFromSeqs(seqs) {
  const m = new Map()
  if (!Array.isArray(seqs)) return m
  for (const seq of seqs) {
    if (!Array.isArray(seq)) continue
    for (const v of seq) {
      const k = `node${v}`
      m.set(k, (m.get(k) || 0) + 1)
    }
  }
  return m
}

function getRegionSequences(regionId, payload, fallback = []) {
  const pl = payload || payloadStore.payload
  const region = regionStore.regions[regionId]
  if (!region) return fallback

  if (Array.isArray(region.sequences) && region.sequences.length > 0) {
    return region.sequences
  }
  if (Array.isArray(region.baseRawSeqs) && region.baseRawSeqs.length > 0) {
    return region.baseRawSeqs
  }
  if (Array.isArray(region.sequenceIds) && region.sequenceIds.length > 0) {
    const fullRaw = pl?.raw_sequences || []
    return region.sequenceIds.map(i => fullRaw[i]).filter(Boolean)
  }
  return fallback
}

function mergeSequencesForOverlay(targetSeqs, baseSeqs) {
  const seen = new Set()
  const merged = []
  for (const seq of [...(targetSeqs || []), ...(baseSeqs || [])]) {
    if (!Array.isArray(seq)) continue
    const key = JSON.stringify(seq)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(seq)
  }
  return merged
}

function hasVisibleHighOrderStates(glyph, cls) {
  const g = glyph?.[String(cls)]
  if (!g) return false
  if (Array.isArray(g.full_order_states)) return g.full_order_states.length > 0
  return (g.unique_states || []).length > 0
}

let edgeCountBeforeCache = new Map()
let edgeCountAfterCache = new Map()
let nodeCountBeforeCache = new Map()
let nodeCountAfterCache = new Map()
let hasBeforeEdgeCountCache = false

function refreshEdgeCountCaches(data, afterSequences = null) {
  const pl = data || payloadStore.payload
  if (!pl) {
    edgeCountBeforeCache = new Map()
    edgeCountAfterCache = new Map()
    nodeCountBeforeCache = new Map()
    nodeCountAfterCache = new Map()
    hasBeforeEdgeCountCache = false
    return
  }
  const seqs = afterSequences ?? props.externalSequences ?? pl.raw_sequences ?? []
  const ridForCounts = props.regionId
  const regionForCounts = regionStore.regions[ridForCounts]

  if (props.overlayBaseRegionId) {
    const beforeSequences = getRegionSequences(props.overlayBaseRegionId, pl, [])
    edgeCountAfterCache = buildEdgeCountFromSeqs(seqs)
    edgeCountBeforeCache = buildEdgeCountFromSeqs(beforeSequences)
    nodeCountAfterCache = buildNodeCountFromSeqs(seqs)
    nodeCountBeforeCache = buildNodeCountFromSeqs(beforeSequences)
    hasBeforeEdgeCountCache = edgeCountBeforeCache.size > 0 || nodeCountBeforeCache.size > 0
    return
  }

  // “过滤前”来源必须稳定：优先使用该 region 已保存的 sourceRegionId（apply 时写入）
  // preview 是全局单例，可能来自其它 panel 的交互；只有当 activePanelRegionId 命中本 panel 时才可用
  const previewObj =
      brushStore.preview?.value ?? brushStore.preview
  const previewSourceRidForThisPanel = previewObj?.sourceRid || null
  const effectiveSourceRid =
      regionForCounts?.sourceRegionId ??
      props.sourceRegionId ??
      previewSourceRidForThisPanel

  let beforeSequences = []
  if (!effectiveSourceRid || effectiveSourceRid === "global") {
    beforeSequences = pl.raw_sequences || []
  } else if (effectiveSourceRid) {
    const sourceRegion = regionStore.regions[effectiveSourceRid]
    if (Array.isArray(sourceRegion?.sequences) && sourceRegion.sequences.length > 0) {
      beforeSequences = sourceRegion.sequences
    } else if (Array.isArray(sourceRegion?.baseRawSeqs) && sourceRegion.baseRawSeqs.length > 0) {
      beforeSequences = sourceRegion.baseRawSeqs
    } else if (Array.isArray(sourceRegion?.sequenceIds) && sourceRegion.sequenceIds.length > 0) {
      const fullRaw = pl.raw_sequences || []
      beforeSequences = sourceRegion.sequenceIds
          .map(i => fullRaw[i])
          .filter(Boolean)
    } else {
      beforeSequences = []
    }
  }

  // 兜底：避免 before 空导致差分失效（常见于 sourceRegion 尚未写入序列子集的时序）
  if (!Array.isArray(beforeSequences) || beforeSequences.length === 0) {
    beforeSequences = pl.raw_sequences || []
  }
  edgeCountAfterCache = buildEdgeCountFromSeqs(seqs)
  edgeCountBeforeCache = buildEdgeCountFromSeqs(beforeSequences)
  nodeCountAfterCache = buildNodeCountFromSeqs(seqs)
  nodeCountBeforeCache = buildNodeCountFromSeqs(beforeSequences)
  hasBeforeEdgeCountCache = edgeCountBeforeCache.size > 0 || nodeCountBeforeCache.size > 0
}

function patchHighlightMetricsOnly() {
  refreshEdgeCountCaches(currentPayloadData())
  updateHighlightStylesFn.value?.()
}

// 首次渲染
onMounted(() => {
  const data = currentPayloadData()
  if (data) {
    renderGraph(data)
  }
})

/* ===============================
 * watch render
 * =============================== */
watch(
    () => regionStore.regions[props.regionId]?.highlightNodes,
    () => {
      updateHighlightStylesFn.value?.()
    }
)

watch(
    () => regionStore.regions[props.regionId]?.highlightEdges,
    () => {
      updateHighlightStylesFn.value?.()
    }
)

watch(
    () => props.externalSequences,
    (seqs, oldSeqs) => {
      // ⭐ 只有当序列“真正变化”时才重绘，避免仅因切换 brush/activeRegion 重新跑力导向
      if (seqs === oldSeqs) return

      if (Array.isArray(seqs) && Array.isArray(oldSeqs)) {
        if (seqs.length === oldSeqs.length) {
          let same = true
          for (let i = 0; i < seqs.length; i++) {
            if (seqs[i] !== oldSeqs[i]) { // 引用层面比较每条子序列
              same = false
              break
            }
          }
          if (same) return
        }
      }

      const data = currentPayloadData()
      if (!data) return
      renderGraph(data)
    }
)

watch(
    () => props.overlayBaseRegionId,
    () => {
      const data = currentPayloadData()
      if (!data) return
      renderGraph(data)
    }
)

watch(
    () => props.payloadData,
    () => {
      const data = currentPayloadData()
      if (!data) return
      renderGraph(data)
    }
)

watch(
    () => payloadStore.highOrderLayoutMode,
    () => {
      const data = currentPayloadData()
      if (!data) return
      renderGraph(data)
    }
)

// preview / sourceRegion 只影响差分边频与高亮，不应触发整图重算 FA2
watch(
    () => [
      regionStore.regions[props.regionId]?.sourceRegionId,
      props.overlayBaseRegionId,
      regionStore.overlay?.baseRegionId,
      regionStore.overlay?.targetRegionId,
      brushStore.preview?.sourceRid,
      brushStore.preview?.updatedAt
    ],
    () => {
      patchHighlightMetricsOnly()
    }
)

/* ===============================
 * render
 * =============================== */
let currentSimulation = null; // 顶层引用

function renderGraph(data) {
  let hoverNodeId = null
  let hoverEdgeKey = null
  noVisibleNodes.value = false

  const measuredWidth = svgRef.value?.clientWidth || 0
  const measuredHeight = svgRef.value?.clientHeight || 0
  if (measuredWidth < 80 || measuredHeight < 80) {
    requestAnimationFrame(() => {
      const latest = currentPayloadData()
      if (latest) renderGraph(latest)
    })
    return
  }

  // 1. 杀掉旧的物理引擎
  if (currentSimulation) {
    currentSimulation.stop();
  }

  // 2. 清空画布
  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const graph = data.graph
  const glyph = data.glyph
  const legend = data.legend

  // ✅ sequences 来源；overlay 时显示 target/base 的 union，保证 A > B 的边也能显示
  const targetSequences =
      props.externalSequences ??
      data.raw_sequences
  const overlayBaseSequences = props.overlayBaseRegionId
      ? getRegionSequences(props.overlayBaseRegionId, data, [])
      : []
  const sequences = props.overlayBaseRegionId
      ? mergeSequencesForOverlay(targetSequences, overlayBaseSequences)
      : targetSequences

  refreshEdgeCountCaches(data, targetSequences)

  // 同时支持 0 和 "node0"
  const activeNodeSet = new Set()
  sequences.forEach(seq => {
    seq.forEach(v => {
      activeNodeSet.add(v)                // 0
      activeNodeSet.add(String(v))        // "0"
      activeNodeSet.add(`node${v}`)       // "node0"
    })
  })

  const width = measuredWidth
  const height = measuredHeight

  // 普通子图复用全局图坐标，便于用户对照同一批 HON 节点；
  // re-aggregate 后的本地模型节点语义已经改变，必须重新布局。
  const isLocalModel = Boolean(props.payloadData)
  const useLayeredLayout = payloadStore.highOrderLayoutMode === "layered"
  const posById = !isLocalModel ? (payloadStore.globalGraphNodePositions || null) : null
  const useGlobalLayout = !useLayeredLayout && !isLocalModel && posById && Object.keys(posById).length > 0

  const root = svg.append("g")

  const zoom = d3.zoom()
      .scaleExtent([0.1,4])
      .on("zoom", e=>{
        root.attr("transform", e.transform)
      })

  svg.call(zoom)
  // ⭐ 初始缩放
  svg.call(
      zoom.transform,
      d3.zoomIdentity
          .translate(width / 4, height / 4)
          .scale(0.5)
  )

  // clone
  // const nodes = graph.nodes.map(d=>({...d}))
  // const links = graph.links.map(d=>({...d}))

  function getId(x) {
    return typeof x === "object" ? x.id : x
  }

  // sequences 里出现过的 node id
  const nodes = data.graph.nodes
      .filter(d =>
          (activeNodeSet.has(d.id) || activeNodeSet.has(String(d.id))) &&
          hasVisibleHighOrderStates(glyph, d.class)
      )
      .map(d => ({ ...d }))
  const visibleNodeIds = new Set(nodes.map(d => String(d.id)))
  if (nodes.length === 0) {
    noVisibleNodes.value = true
    return
  }

  const linkMap = new Map()
  const rejectedLinks = []
  const addVisibleLink = (source, target, value = 1, { onlyIfMissing = false } = {}) => {
    const s = toGraphNodeId(source)
    const t = toGraphNodeId(target)
    if (!s || !t) {
      rejectedLinks.push({ source, target, reason: "empty endpoint" })
      return
    }
    if (!visibleNodeIds.has(s) || !visibleNodeIds.has(t)) {
      rejectedLinks.push({
        source,
        target,
        normalizedSource: s,
        normalizedTarget: t,
        reason: "endpoint not visible"
      })
      return
    }
    const k = `${s}→${t}`
    if (onlyIfMissing && linkMap.has(k)) return
    if (!linkMap.has(k)) {
      linkMap.set(k, {
        source: s,
        target: t,
        value: 0
      })
    }
    linkMap.get(k).value += Number(value) || 1
  }

  const graphLinks = Array.isArray(graph?.links) ? graph.links : []
  const visibleSequenceSamples = []
  if (isLocalModel && graphLinks.length > 0) {
    graphLinks.forEach(l => addVisibleLink(l.source, l.target, l.value))
  }

  // Re-aggregate 会隐藏 warm-up(-1) 节点；若直接按原序列相邻点画边，很多边会被 -1 吃掉。
  // 这里在本地模型中跳过不可见节点，补齐相邻可见高阶聚合节点之间的边。
  if (isLocalModel) {
    sequences.forEach((seq, seqIndex) => {
      const visibleSeq = []
      for (const v of seq || []) {
        const id = toGraphNodeId(v)
        if (id && visibleNodeIds.has(id)) visibleSeq.push(id)
      }
      if (visibleSequenceSamples.length < 6) {
        visibleSequenceSamples.push({
          seqIndex,
          raw: shortList(seq, 12),
          visible: shortList(visibleSeq, 12),
          rawLength: Array.isArray(seq) ? seq.length : 0,
          visibleLength: visibleSeq.length
        })
      }
      for (let i = 0; i < visibleSeq.length - 1; i++) {
        addVisibleLink(visibleSeq[i], visibleSeq[i + 1], 1, { onlyIfMissing: true })
      }
    })
  } else {
    sequences.forEach(seq => {
      for (let i = 0; i < seq.length - 1; i++) {
        addVisibleLink(seq[i], seq[i + 1], 1)
      }
    })
  }

  const links = Array.from(linkMap.values())

  if (isLocalModel) {
    const duplicateEdgeKeys = links
        .map(l => `${l.source}→${l.target}`)
        .filter((key, index, arr) => arr.indexOf(key) !== index)
    const edgeBuildDebug = {
      regionId: props.regionId || "unknown",
      modelInfo: props.payloadData?.model_info || null,
      graphNodes: data.graph?.nodes?.length || 0,
      visibleNodes: nodes.length,
      visibleNodeIds: shortList(Array.from(visibleNodeIds), 20),
      sequenceCount: Array.isArray(sequences) ? sequences.length : 0,
      sequenceSamples: visibleSequenceSamples,
      graphLinks: graphLinks.length,
      finalVisibleLinks: links.length,
      duplicateEdgeKeys: shortList(duplicateEdgeKeys, 12),
      finalSamples: shortList(links, 12),
      rejectedCount: rejectedLinks.length,
      rejectedSamples: shortList(rejectedLinks, 12)
    }
    console.log(`[ForceGraph Debug JSON] edge-build ${JSON.stringify(edgeBuildDebug)}`)
    if (links.length === 0) {
      console.warn(`[ForceGraph Debug Warning] region=${props.regionId || "unknown"} finalVisibleLinks=0`, edgeBuildDebug)
    }
  }


  /* ===============================
   * out / in map
   * =============================== */

  const outMap = new Map()
  const inMap = new Map()

  links.forEach(l=>{
    const s = typeof l.source==="object"?l.source.id:l.source
    const t = typeof l.target==="object"?l.target.id:l.target

    if(!outMap.has(s)) outMap.set(s,[])
    if(!inMap.has(t)) inMap.set(t,[])

    outMap.get(s).push(l)
    inMap.get(t).push(l)
  })

  nodes.forEach(n=>{
    const outLs = outMap.get(n.id) || []

    n.outFlow = d3.sum(outMap.get(n.id)||[],d=>d.value)
    n.inFlow  = d3.sum(inMap.get(n.id)||[],d=>d.value)
    n.entropy = entropyFromLinks(outLs)
  })

  const maxEntropy = d3.max(nodes, d => d.entropy) || 1
  const entropyColor = d3.scaleSequential(d3.interpolateYlOrRd)
      .domain([0, maxEntropy])

  const outDegrees = nodes.map(
      d => outMap.get(d.id)?.length || 0
  )

  const outScale = d3.scaleLinear()
      .domain(d3.extent(outDegrees))
      .range([0.8, 1.8])   // 0.8-1.8出度低的紧凑

  const rScale = d3.scaleLinear()
      .domain(d3.extent(outDegrees))
      .range([300, 60])   // 低出度 → 外圈；高出度 → 中心

  /* ===============================
   * layer
   * =============================== */

  const layerMap = computeLayerMap(sequences)
  const maxLayer =
      d3.max(nodes,d=>layerMap.get(String(d.class))||0)||1

  const xScale =
      d3.scaleLinear()
          .domain([0,maxLayer])
          .range([40,width-40])

  nodes.forEach(n=>{
    const L = layerMap.get(String(n.class))||0
    n.x = xScale(L)+(Math.random()-0.5)*20
    n.y = height/2+(Math.random()-0.5)*80
  })

  /* ===============================
   * link color & opacity (与 GraphGlyph 保持一致)
   * =============================== */

  const values = links.map(d => d.value)
  const minV = d3.min(values)
  const maxV = d3.max(values)

  const rid = props.regionId
  const regionBrushId = regionStore.regions[rid]?.brushId
  const regionBrushColor = brushStore.brushes?.[regionBrushId]?.color || null

  const v0 = (minV === maxV) ? 0 : (minV ?? 0);
  const v1 = (minV === maxV) ? (maxV ?? 1) : (maxV ?? 1);

  // 子图边颜色：默认用 region 的 brush 同色系（浅色 -> 深色）；若无 brush 则回退灰色
  const lightBrushColor = regionBrushColor
      ? d3.hsl(regionBrushColor).brighter(1.1).formatRgb() // 1.5 表示变亮程度，可以根据需要调整
      : "#eeeeee";

  const darkBrushColor = regionBrushColor || "#444444"

  const linkColor = d3.scalePow()
      .exponent(0.8)
      .domain([v0, v1])
      .range([lightBrushColor, darkBrushColor])
      .clamp(true)

  const linkOpacity = d3.scalePow()
      .exponent(0.8)
      .domain([v0, v1])
      .range([0.2, 1])
      .clamp(true)

  const linkSel = root.append("g")
      .attr("class", "edge-fill-layer")
      .selectAll("path")
      .data(links)
      .enter()
      .append("path")
      .attr("fill", d => {
        const sid = d.source
        const tid = d.target
        return sid === tid ? "none" : linkColor(d.value)
      })
      .attr("stroke", d => {
        const sid = d.source
        const tid = d.target
        return sid === tid ? linkColor(d.value) : "none"
      })
      .attr("stroke-width", d => {
        const sid = d.source
        const tid = d.target
        return sid === tid ? 2 : 0
      })
      .attr("stroke-linecap", "round")
      .attr("opacity", d => {
        return linkOpacity(d.value)})

  // Keep one visual mark per logical edge. The tapered path already encodes the
  // edge body; drawing an additional center line makes a single aggregated edge
  // look like multiple parallel edges between the same two nodes.
  const linkLineSel = root.append("g")
      .attr("class", "edge-stroke-layer")
      .selectAll("path")
      .data([])

  linkSelRef.value = linkSel
  linkLineSelRef.value = linkLineSel

  /* ===============================
   * brush click
   * =============================== */
  linkSel
      .on("mouseenter", function(event, d) {
        d3.select(this).style("cursor", "pointer")

        showTooltip(
            `
      ${d.source.class} → ${d.target.class}<br/>
      value: ${d.value}
      `,
            event
        )
      })
      .on("mouseleave", function() {
        hideTooltip()
      })
      .on("click",(event,d)=>{
        // 标明我在对哪个子图进行brush
        event.stopPropagation()
        if (brushStore.interactionMode !== "brush") return
        brushStore.setActivePanelRegion(props.regionId, "region")
        if(!brushStore.activeBrushId) brushStore.createBrush()
        if (!brushStore.canEditActiveBrushFromRegion(props.regionId)) return

        brushStore.toggleEdge(
            brushStore.activeBrushId,
            edgeKey(d)
        )
      })

  /* ===============================
   * nodes
   * =============================== */
  const NODE_W = 60
  const NODE_H = 25

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

  nodeSelRef.value=nodeSel

  nodeSel
      .on("mouseenter", function(event, d) {
        d3.select(this).style("cursor", "pointer")
        hoverNodeId = d.id
        hoverEdgeKey = null

        updateHighlightStylesFn.value?.()

        showTooltip(
            `
          class: ${d.class}<br/>
<!--          entropy: ${d.entropy.toFixed(3)}<br/>-->
          out-flow: ${d.outFlow}<br/>
          in-flow: ${d.inFlow}
          `,
            event
        )
      })
      .on("mouseleave", function() {
        // 恢复为按权重映射的透明度
        hoverNodeId = null

        updateHighlightStylesFn.value?.()
        hideTooltip()
      })
      .on("click", (event, d) => {
        event.stopPropagation()
        if (props.regionId && regionStore.activeRegionId !== props.regionId) {
          regionStore.setActive(props.regionId)
        }
        payloadStore.toggleHighOrderClass(String(d.class), props.regionId || "global")
        if (brushStore.interactionMode === "brush") {
          brushStore.setActivePanelRegion(props.regionId, "region")
          if (!brushStore.activeBrushId) brushStore.createBrush()
          if (!brushStore.canEditActiveBrushFromRegion(props.regionId)) return
          brushStore.addClass(String(d.class))
        }
      })

  nodeSel.append("rect")
      .attr("x",-NODE_W/2)
      .attr("y",-NODE_H/2)
      .attr("width",NODE_W)
      .attr("height",NODE_H)
      .attr("rx",6)
      .attr("fill","#f5f5f5")
      .attr("stroke", d => entropyColor(d.entropy))
      .attr("stroke-width", d => 0.9 + d.entropy * 1.4)

  nodeSel.append("text")
      .attr("x",-NODE_W/2-6)
      .attr("y",0)
      .attr("text-anchor","end")
      .attr("dominant-baseline","middle")
      .style("font-size","11px")
      .text(d=>d.class)

  drawGlyphForce(
      nodeSel,
      glyph,
      legend.tokens,
      payloadStore.colorScale,
      NODE_W,
      NODE_H
  )

  const nodeById = new Map(nodes.map(n => [n.id, n]))

  // 如果全局图已有节点布局坐标，则直接复用，子图只做刚性平移（不再跑 FA2）
  // 这样可以保证相同节点在全局/子图里的相对布局一致。
  let usedGlobalLayout = false
  if (useGlobalLayout) {
    let matched = 0
    const total = nodes.length
    nodes.forEach(n => {
      const key = String(n.id)
      const p = posById?.[key]
      if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) {
        n.x = p.x
        n.y = p.y
        matched++
      }
    })
    // 需要匹配到足够多节点，否则 fallback 到原来的 FA2 布局，避免出现未定义坐标导致布局异常
    usedGlobalLayout = matched >= Math.max(1, Math.floor(total * 0.8))
  }

  /* ===============================
  * ForceAtlas2 布局（Gephi style）
  * =============================== */
  if (!usedGlobalLayout) {
    if (useLayeredLayout) {
      applyLayeredLayout(nodes, links, {
        nodeW: NODE_W * 0.62,
        nodeH: NODE_H,
        ranksep: 18,
        nodesep: 14,
      })
    } else {
    const g = new Graph({
      multi: true,
      type: "directed",
      allowSelfLoops: true
    })

  const xNorm = d3.scaleLinear()
      .domain([0, maxLayer])
      .range([-500, 500])

  /* -------------------------------
   * 初始化位置（Gephi风格）
   * ------------------------------- */
  const baseSize =
      Math.sqrt(NODE_W * NODE_W + NODE_H * NODE_H) / 2

  nodes.forEach(n => {

    const L = layerMap.get(String(n.class)) ?? 0

    // 1. 缩小初始随机范围
    const initX = xNorm(L) * 0.5 + (Math.random() - 0.5) * 100
    const initY = (Math.random() - 0.5) * 100


    n.x = initX
    n.y = initY

    const degree =
        (outMap.get(n.id)?.length || 0) +
        (inMap?.get?.(n.id)?.length || 0)

    const baseSize =
        Math.sqrt(NODE_W * NODE_W + NODE_H * NODE_H) / 2

    g.addNode(n.id, {
      ...n,
      x: initX,
      y: initY,

      // ⭐ size 必须大，否则 adjustSizes 无效
      size: baseSize
    })

  })

  /* -------------------------------
   * 边
   * ------------------------------- */

  links.forEach((l, i) => {

    const sid = getId(l.source)
    const tid = getId(l.target)

    if (!g.hasNode(sid) || !g.hasNode(tid)) return

    g.addDirectedEdgeWithKey(
        `${sid}→${tid}#${i}`,
        sid,
        tid,
        {
          weight: 1 / (l.value)
        }
    )

  })

    /* -------------------------------
     * Gephi 风格 FA2 参数
     * ------------------------------- */
    const fa2Settings = {
    // 应该改为 true 让重要节点在中心
    linLogMode: false,  // false ❌
    outboundAttractionDistribution: true,  // ✅ 这个正确
    adjustSizes: true,  // true ❌ 先关闭
    gravity: 1,  // Gephi默认是1 ✅
    scalingRatio: 2000 * (20 / Math.max(nodes.length, 1)),
    strongGravityMode: true,  // false ❌ 打开强引力让节点向中心聚集
    slowDown: 1,  // 10 ❌ 太大导致移动太慢
    barnesHutOptimize: true,
    barnesHutTheta: 1.2,
    edgeWeightInfluence: 0
  }


  /* -------------------------------
   * 多次迭代（更像 Gephi）
   * ------------------------------- */

    forceAtlas2.assign(g, {
      iterations: 20000,
      settings: fa2Settings
    })


    /* -------------------------------
     * 写回坐标
     * ------------------------------- */
    nodes.forEach(n => {
      n.x = g.getNodeAttribute(n.id, "x")
      n.y = g.getNodeAttribute(n.id, "y")
    })
    }
  }


  /* -------------------------------
  * Gephi风格 scale（支持矩形容器）
  * ------------------------------- */
  const xs = nodes.map(d => d.x)
  const ys = nodes.map(d => d.y)

  const minX = d3.min(xs) ?? -1
  const maxX = d3.max(xs) ?? 1

  const minY = d3.min(ys) ?? -1
  const maxY = d3.max(ys) ?? 1

  // ⭐ 节点尺寸需要留空间
  const nodePadX = NODE_W * 3
  const nodePadY = NODE_H * 3

  const padding = 40

  const availableW =
      width - padding * 2 - nodePadX * 2

  const availableH =
      height - padding * 2 - nodePadY * 2


  const layoutW = (maxX - minX) || 1
  const layoutH = (maxY - minY) || 1

  const scale = useLayeredLayout ? 0.52 : 1

  nodes.forEach(n => {

    const nx = (n.x - minX) * scale
    const ny = (n.y - minY) * scale

    n.x =
        nx +
        padding +
        nodePadX +
        (availableW - layoutW * scale) / 2

    n.y =
        ny +
        padding +
        nodePadY +
        (availableH - layoutH * scale) / 2

  })

  resolveNodeOverlaps(
      nodes,
      NODE_W,
      NODE_H,
      8,
      6,
      Math.min(520, Math.max(80, nodes.length * 5))
  )
  /* -------------------------------
   * 写回 link
   * ------------------------------- */

  const missingMappedLinks = []
  links.forEach(l => {

    l.source = nodeById.get(getId(l.source))
    l.target = nodeById.get(getId(l.target))
    if (!l.source || !l.target) {
      missingMappedLinks.push({
        source: getId(l.source),
        target: getId(l.target),
        value: l.value
      })
    }

  })
  if (isLocalModel && missingMappedLinks.length > 0) {
    console.warn(`[ForceGraph Debug] region=${props.regionId || "unknown"} links missing node objects`, shortList(missingMappedLinks, 12))
  }

  function refreshPositions() {
    const getX = (n) => (n.fx != null ? n.fx : n.x)
    const getY = (n) => (n.fy != null ? n.fy : n.y)
    let fillPathCount = 0
    let linePathCount = 0
    linkSel.attr("d", d => {
      if (!d.source || !d.target) return ""
      const sid = d.source.id
      const tid = d.target.id
      const d2 = {
        ...d,
        source: { ...d.source, x: getX(d.source), y: getY(d.source) },
        target: { ...d.target, x: getX(d.target), y: getY(d.target) }
      }
      if (sid === tid) return selfLoopTaperedPath(d2, NODE_W, NODE_H)
      const path = curvedTaperedLinkPath(d2, 3, 1)
      if (path && !path.includes("NaN")) fillPathCount++
      return path
    })
    linkLineSel.attr("d", () => "")
    nodeSel.attr("transform", d => {
      const x = getX(d)
      const y = getY(d)
      return `translate(${x},${y})`
    })
    if (isLocalModel) {
      const renderDebug = {
        regionId: props.regionId || "unknown",
        links: links.length,
        fillPathCount,
        linePathCount,
        edgeFillDomCount: linkSel.size(),
        edgeLineDomCount: linkLineSel.size(),
        firstNodePositions: shortList(nodes.map(n => ({
          id: n.id,
          x: Number.isFinite(n.x) ? Number(n.x.toFixed(2)) : n.x,
          y: Number.isFinite(n.y) ? Number(n.y.toFixed(2)) : n.y
        })), 8)
      }
      console.log(`[ForceGraph Debug JSON] rendered-paths ${JSON.stringify(renderDebug)}`)
      if (links.length > 0 && linePathCount === 0 && fillPathCount === 0) {
        console.warn(`[ForceGraph Debug Warning] region=${props.regionId || "unknown"} links exist but no paths rendered`, renderDebug)
      }
    }
  }
  refreshPositions()

  function dragstarted(event, d) {
    d.fx = d.x
    d.fy = d.y
    d3.select(event.sourceEvent?.target)?.style("cursor", "grabbing")
  }
  function dragged(event, d) {
    d.fx = event.x
    d.fy = event.y
    refreshPositions()
  }
  function dragended(event, d) {
    d.fx = null
    d.fy = null
    d.x = event.x
    d.y = event.y
    refreshPositions()
    d3.select(event.sourceEvent?.target)?.style("cursor", null)
  }

  function updateHighlightStyles() {
    const rid = props.regionId
    const r = regionStore.regions[rid]

    const highlightNodes = r?.highlightNodes ?? new Set()
    const highlightEdges = r?.highlightEdges ?? new Set()

    const hasHighlight =
        highlightNodes.size > 0 ||
        highlightEdges.size > 0
    const hasEdgeHighlight = highlightEdges.size > 0

    const active = brushStore.activeBrush
    const previewObj = brushStore.preview?.value ?? brushStore.preview
    const effectiveSourceRid =
        r?.sourceRegionId ??
        props.sourceRegionId ??
        previewObj?.sourceRid ??
        null

    const sourceBrushId = r?.brushId

    const sourceBrushColor =
        sourceBrushId && sourceBrushId !== "global"
            ? (brushStore.brushes?.[sourceBrushId]?.color || null)
            : null

    const isOverlayMode = Boolean(props.overlayBaseRegionId)
    const overlayBaseRegion = props.overlayBaseRegionId
        ? regionStore.regions[props.overlayBaseRegionId]
        : null
    const overlayTargetRegion = regionStore.regions[props.regionId]
    const overlayBaseColor =
        overlayBaseRegion?.brushId
            ? (brushStore.brushes?.[overlayBaseRegion.brushId]?.color || "#9a3340")
            : "#9a3340"
    const overlayTargetColor =
        overlayTargetRegion?.brushId
            ? (brushStore.brushes?.[overlayTargetRegion.brushId]?.color || regionBrushColor || "#2f6f9f")
            : (regionBrushColor || "#2f6f9f")

    // diffOpacity：用 |过滤前 - 过滤后| 反映差值大小
    let maxAbsDiff = 0
    const allEdgeKeys = new Set([
      ...edgeCountBeforeCache.keys(),
      ...edgeCountAfterCache.keys()
    ])
    allEdgeKeys.forEach((k) => {
      const absDiff = Math.abs((edgeCountBeforeCache.get(k) || 0) - (edgeCountAfterCache.get(k) || 0))
      if (absDiff > maxAbsDiff) maxAbsDiff = absDiff
    })
    const allNodeKeys = new Set([
      ...nodeCountBeforeCache.keys(),
      ...nodeCountAfterCache.keys()
    ])
    allNodeKeys.forEach((k) => {
      const absDiff = Math.abs((nodeCountBeforeCache.get(k) || 0) - (nodeCountAfterCache.get(k) || 0))
      if (absDiff > maxAbsDiff) maxAbsDiff = absDiff
    })

    const diffOpacity = d3.scalePow()
        .exponent(0.5)
        .domain([0, maxAbsDiff || 1])
        .range([0.1, 1])

    const getBefore = (k) => edgeCountBeforeCache.get(k) || 0
    const getAfter = (k) => edgeCountAfterCache.get(k) || 0
    const getDiff = (k) => getAfter(k) - getBefore(k)
    const getAbsDiff = (k) => Math.abs(getDiff(k))
    const getNodeBefore = (k) => nodeCountBeforeCache.get(k) || 0
    const getNodeAfter = (k) => nodeCountAfterCache.get(k) || 0
    const getNodeDiff = (k) => getNodeAfter(k) - getNodeBefore(k)
    const getNodeAbsDiff = (k) => Math.abs(getNodeDiff(k))
    const pickOverlayColor = (diff, absDiff) => {
      if (diff === 0) return "#b8bec6"
      const baseColor = diff > 0 ? overlayTargetColor : overlayBaseColor
      const lightColor = d3.hsl(baseColor).brighter(1.25).formatRgb()
      return d3.scalePow()
          .exponent(0.8)
          .domain([0, maxAbsDiff || 1])
          .range([lightColor, baseColor])
          .clamp(true)(absDiff)
    }
    const pickHighlightColor = (k, fallback) => {
      const before = getBefore(k)
      const after = getAfter(k)
      // 哪个数据更大就用谁的颜色：刷后(after)大 -> 当前刷子色；刷前(before)大 -> 来源刷子色
      let baseColor = null
      if (after > before && active?.color) baseColor = active.color
      if (before > after && sourceBrushColor) baseColor = sourceBrushColor
      // 相等时优先来源色；无来源色再退当前色
      if (!baseColor && sourceBrushColor) baseColor = sourceBrushColor
      if (!baseColor && active?.color) baseColor = active.color
      if (!baseColor) return fallback

      const lightBrushColor = d3.hsl(baseColor).brighter(1.1).formatRgb()
      const diffColor = d3.scalePow()
          .exponent(0.8)
          .domain([0, maxAbsDiff || 1])
          .range([lightBrushColor, baseColor])
          .clamp(true)
      return diffColor(getAbsDiff(k))
    }

    if (isOverlayMode) {
      nodeSel.select("rect")
          .attr("stroke", d => {
            const diff = getNodeDiff(d.id)
            return pickOverlayColor(diff, Math.abs(diff))
          })
          .attr("stroke-width", d => {
            const absDiff = getNodeAbsDiff(d.id)
            return absDiff === 0 ? 1 : 1 + Math.min(2.5, diffOpacity(absDiff) * 2.5)
          })

      linkSel
          .attr("opacity", d => {
            const absDiff = getAbsDiff(edgeKey(d))
            return diffOpacity(absDiff)
          })
          .attr("fill", d => {
            const sid = d.source
            const tid = d.target
            if (sid === tid) return "none"
            const k = edgeKey(d)
            return pickOverlayColor(getDiff(k), getAbsDiff(k))
          })
          .attr("stroke", d => {
            const sid = d.source
            const tid = d.target
            if (sid !== tid) return "none"
            const k = edgeKey(d)
            return pickOverlayColor(getDiff(k), getAbsDiff(k))
          })
      linkLineSel
          .attr("opacity", d => diffOpacity(getAbsDiff(edgeKey(d))))
          .attr("stroke", d => {
            const k = edgeKey(d)
            return pickOverlayColor(getDiff(k), getAbsDiff(k))
          })
      return
    }

    nodeSel.select("rect")
        .attr("stroke", d => {
          if (!active) return entropyColor(d.entropy)
          if (!highlightNodes) return entropyColor(d.entropy)
          const hit = highlightNodes.has(d.id)
          return hit ? active.color : entropyColor(d.entropy)
        })
        .attr("stroke-width", d => {
          if (hasHighlight && highlightNodes.has(d.id))
            return 1.5

          if (!hasHighlight && hoverNodeId === d.id)
            return 1.5

          return 0.9 + d.entropy * 1.4
        })

    // 边
    linkSel
        .attr("opacity", d => {
          const k = edgeKey(d)
          // highlight 优先
          if (hasEdgeHighlight) {
            if (!highlightEdges.has(k)) return 0.05
            if (!hasBeforeEdgeCountCache) return 1
            return diffOpacity(getAbsDiff(k))
          }
          // hover 次优先
          if (hoverNodeId) {
            if (
                d.source.id === hoverNodeId ||
                d.target.id === hoverNodeId
            ) return 1
            return 0.05
          }
          if (hoverEdgeKey) {
            return k === hoverEdgeKey ? 1 : 0.05
          }

          // default
          return linkOpacity(d.value)
        })
        .attr("fill", d => {
          const sid = d.source
          const tid = d.target
          if (!hasEdgeHighlight)
            return sid !== tid ? linkColor(d.value) : "none"
          const k = edgeKey(d)
          if (!highlightEdges.has(k))
            return sid !== tid ? linkColor(d.value) : "none"
          return sid !== tid
              ? pickHighlightColor(k, linkColor(d.value))
              : "none"
        })
        .attr("stroke", d => {
          const sid = d.source
          const tid = d.target
          if (!hasEdgeHighlight)
            return sid === tid ? linkColor(d.value) : "none"
          const k = edgeKey(d)
          if (!highlightEdges.has(k))
            return sid === tid ? linkColor(d.value) : "none"
          return sid === tid
              ? pickHighlightColor(k, linkColor(d.value))
              : "none"
        })

    linkLineSel
        .attr("opacity", d => {
          const k = edgeKey(d)
          if (hasEdgeHighlight) {
            if (!highlightEdges.has(k)) return 0.05
            if (!hasBeforeEdgeCountCache) return 1
            return Math.max(0.45, diffOpacity(getAbsDiff(k)))
          }
          if (hoverNodeId) {
            if (
                d.source.id === hoverNodeId ||
                d.target.id === hoverNodeId
            ) return 1
            return 0.05
          }
          if (hoverEdgeKey) return k === hoverEdgeKey ? 1 : 0.05
          return Math.max(0.45, linkOpacity(d.value))
        })
        .attr("stroke", d => {
          const k = edgeKey(d)
          if (hasEdgeHighlight && highlightEdges.has(k)) {
            return pickHighlightColor(k, linkColor(d.value))
          }
          return linkColor(d.value)
        })
  }

  // ⭐ 新增这一行，把本次 renderGraph 构建的函数绑定到组件级 ref
  updateHighlightStylesFn.value = updateHighlightStyles

  /* ===============================
   * simulation
   * =============================== */

  // const sim = d3.forceSimulation(nodes)
  //     .force("link",
  //         d3.forceLink(links)
  //             .id(d=>d.id)
  //             .distance(260)
  //             .strength(0.15)
  //     )
  //     .force("x",
  //         d3.forceX(d=>{
  //           const L = layerMap.get(String(d.class))||0
  //           return xScale(L)
  //         }).strength(0.2)
  //     )
  //     .force("y",
  //         d3.forceY(height/2).strength(0.2)
  //     )
  //
  //     .force("charge", d3.forceManyBody().strength(-800))
  //     .force("center", d3.forceCenter(width / 2, height / 2))
  //     // .force("collide", d3.forceCollide().radius(Math.max(NODE_W, NODE_H)))
  //     .force("radial", d3.forceRadial(
  //         d => rScale(outMap.get(d.id)?.length || 0),
  //         width / 2,
  //         height / 2
  //     ).strength(0.4))
  //
  //     .force("collide", d3.forceCollide()
  //         .radius(d => {
  //           // 出边多的紧凑
  //           const outDeg = outMap.get(d.id)?.length || 0
  //           return Math.max(NODE_W, NODE_H) * outScale(outDeg)
  //         })
  //     )
  //
  // sim.on("tick",()=>{
  //
  //   linkSel.attr("d",d=>{
  //     if(d.source.id===d.target.id){
  //       return selfLoopTaperedPath(d,NODE_W,NODE_H)
  //     }
  //     return curvedTaperedLinkPath(d,3,1)
  //   })
  //
  //   nodeSel.attr(
  //       "transform",
  //       d=>`translate(${d.x},${d.y})`
  //   )
  // })

  updateHighlightStyles()

}

</script>

<template>
  <div class="force-root">
    <div ref="tooltipRef" class="tooltip"></div>
    <div v-if="noVisibleNodes" class="empty-visible">
      No full-order high-order states in this view.
    </div>
    <svg ref="svgRef"></svg>
  </div>
</template>

<style scoped>
.force-root{
  width:100%;
  height:100%;
  flex: 1;
  min-height: 0;
  position:relative;
}

svg{
  width:100%;
  height:100%;
  border:1px solid #ccc;
  background:white;
}

.tooltip {
  position: fixed;
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
  z-index: 100000;
}

.empty-visible {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
  pointer-events: none;
}
svg {
  background: transparent !important;
}
</style>

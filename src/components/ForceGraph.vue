<script setup>
import { ref, watch, onMounted } from "vue"
import * as d3 from "d3"
import {entropyFromLinks} from "./tool.js";
import { useRegionStore } from "@/store/regionStore.js"  // ⭐ 新增

import {
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
  regionId: String,
  sourceRegionId: String,   // ⭐ 新增
})

/* ===============================
 * refs
 * =============================== */

const svgRef = ref(null)
const nodeSelRef = ref(null)
const linkSelRef = ref(null)
const tooltipRef = ref(null)
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

let edgeCountBeforeCache = new Map()
let edgeCountAfterCache = new Map()
let hasBeforeEdgeCountCache = false

function refreshEdgeCountCaches(data) {
  const pl = data || payloadStore.payload
  if (!pl) {
    edgeCountBeforeCache = new Map()
    edgeCountAfterCache = new Map()
    hasBeforeEdgeCountCache = false
    return
  }
  const seqs = props.externalSequences ?? pl.raw_sequences ?? []
  const ridForCounts = props.regionId
  const regionForCounts = regionStore.regions[ridForCounts]
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
  hasBeforeEdgeCountCache = edgeCountBeforeCache.size > 0
}

function patchHighlightMetricsOnly() {
  refreshEdgeCountCaches(payloadStore.payload)
  updateHighlightStylesFn.value?.()
}

// 首次渲染
onMounted(() => {
  if (payloadStore.payload) {
    renderGraph(payloadStore.payload)
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

      renderGraph(payloadStore.payload)
    }
)

// preview / sourceRegion 只影响差分边频与高亮，不应触发整图重算 FA2
watch(
    () => [
      regionStore.regions[props.regionId]?.sourceRegionId,
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

  // ✅ sequences 来源
  const sequences =
      props.externalSequences ??
      data.raw_sequences

  refreshEdgeCountCaches(data)

  // 同时支持 0 和 "node0"
  const activeNodeSet = new Set()
  sequences.forEach(seq => {
    seq.forEach(v => {
      activeNodeSet.add(v)                // 0
      activeNodeSet.add(String(v))        // "0"
      activeNodeSet.add(`node${v}`)       // "node0"
    })
  })

  const width = svgRef.value.clientWidth
  const height = svgRef.value.clientHeight

  // 子图不再复用全局图坐标：始终使用当前子图自己的 FA2 布局
  const posById = null
  const useGlobalLayout = false

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
      .filter(d => activeNodeSet.has(d.id) || activeNodeSet.has(String(d.id)))
      .map(d => ({ ...d }))

  const linkMap = new Map()

  sequences.forEach(seq => {
    for (let i = 0; i < seq.length - 1; i++) {

      const s = `node${seq[i]}`
      const t = `node${seq[i+1]}`
      const k = `${s}→${t}`

      if (!linkMap.has(k)) {
        linkMap.set(k, {
          source: s,
          target: t,
          value: 0
        })
      }

      linkMap.get(k).value += 1
    }
  })

  const links = Array.from(linkMap.values())


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


  linkSelRef.value = linkSel

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
        brushStore.setActivePanelRegion(props.regionId, "region")
        event.stopPropagation()
        if(!brushStore.activeBrushId) return

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
        brushStore.setActivePanelRegion(props.regionId, "region")
        // toggleClass 内部已触发 commit，避免重复提交导致异步返回乱序覆盖高亮
        brushStore.toggleClass(String(d.class))
      })

  nodeSel.append("rect")
      .attr("x",-NODE_W/2)
      .attr("y",-NODE_H/2)
      .attr("width",NODE_W)
      .attr("height",NODE_H)
      .attr("rx",6)
      .attr("fill","#f5f5f5")
      .attr("stroke","#999")

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
    const g = new Graph({
      multi: true,
      type: "directed",
      allowSelfLoops: true
    })

  const xNorm = d3.scaleLinear()
      .domain([0, maxLayer])
      .range([-500, 500])   // ⭐ 不再是 0~1

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
    scalingRatio: 1500 *  500/Math.pow(nodes.length, 2),   // 10 ❌ 太大导致过于分散
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

  const scale = 1

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
  /* -------------------------------
   * 写回 link
   * ------------------------------- */

  links.forEach(l => {

    l.source = nodeById.get(getId(l.source))
    l.target = nodeById.get(getId(l.target))

  })

  function refreshPositions() {
    const getX = (n) => (n.fx != null ? n.fx : n.x)
    const getY = (n) => (n.fy != null ? n.fy : n.y)
    linkSel.attr("d", d => {
      const sid = d.source.id
      const tid = d.target.id
      const d2 = {
        ...d,
        source: { ...d.source, x: getX(d.source), y: getY(d.source) },
        target: { ...d.target, x: getX(d.target), y: getY(d.target) }
      }
      if (sid === tid) return selfLoopTaperedPath(d2, NODE_W, NODE_H)
      return curvedTaperedLinkPath(d2, 3, 1)
    })
    nodeSel.attr("transform", d => {
      const x = getX(d)
      const y = getY(d)
      return `translate(${x},${y})`
    })
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

    const diffOpacity = d3.scalePow()
        .exponent(0.5)
        .domain([0, maxAbsDiff || 1])
        .range([0.1, 1])

    const getBefore = (k) => edgeCountBeforeCache.get(k) || 0
    const getAfter = (k) => edgeCountAfterCache.get(k) || 0
    const getDiff = (k) => getAfter(k) - getBefore(k)
    const getAbsDiff = (k) => Math.abs(getDiff(k))
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

    nodeSel.select("rect")
        .attr("stroke", d => {
          if (!active) return "#aaa"
          if (!highlightNodes) return "#aaa"
          const hit = highlightNodes.has(d.id)
          return hit ? active.color : "#aaa"
        })
        .attr("stroke-width", d => {
          if (hasHighlight && highlightNodes.has(d.id))
            return 1.5

          if (!hasHighlight && hoverNodeId === d.id)
            return 1.5

          return 1
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
    <svg ref="svgRef"></svg>
  </div>
</template>

<style scoped>
.force-root{
  width:100%;
  height:100%;
  position:relative;
}

svg{
  width:100%;
  height:100%;
  border:1px solid #ccc;
  background:white;
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
svg {
  background: transparent !important;
}
</style>

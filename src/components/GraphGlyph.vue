<script setup>
import {ref, watch, computed } from "vue"
import { Upload } from "@element-plus/icons-vue"
import * as d3 from "d3"
import {
  applyLayeredLayout,
  computeLayerMap,
  selfLoopTaperedPath,
  curvedTaperedLinkPath,
  entropyFromLinks
} from "./tool.js";
import { usePayloadStore } from "@/store/payloadStore.js"
import { useBrushStore } from "@/store/brushStore.js"
import { drawGlyphForce } from "./drawGlyphForce.js"
import { useRegionStore } from "@/store/regionStore.js"
import { apiUrl } from "@/api"
import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"
// ⭐ 新增：导入图片
import sliceIcon from "../assets/slice.svg"

/* ===============================
 * refs
 * =============================== */
const svgRef = ref(null)
const nodeSelRef = ref(null)
const linkSelRef = ref(null) // 可选
const file = ref(null)
const payload = ref(null)
const tooltipRef = ref(null)
const payloadStore = usePayloadStore()
const fileInput = ref(null)
const linkGrayRef = ref(null)
const clusterFile = ref(null)
// ⭐ 弹窗相关状态
const showDialog = ref(false)
const dialogNodeClass = ref(null)
const inputNumber = ref(null)
const dialogX = ref(0)
const dialogY = ref(0)

const brushStore = useBrushStore()
const regionStore = useRegionStore()
const updateHighlightStylesFn = ref(null)  // ⭐ 新增

watch(
    () => regionStore.regions["global"]?.highlightNodes,
    () => {

      updateHighlightStylesFn.value?.()
    },
    { deep: true }
)

watch(
    () => [
	      payloadStore.selectedHighOrderClass,
	      payloadStore.selectedHighOrderRegionId,
	      payloadStore.selectedFirstOrderState,
	      payloadStore.selectedFirstOrderRegionId,
	      payloadStore.hoveredAppendEvent,
      payloadStore.focusedAppendEvent,
      payloadStore.hoveredHighOrderClasses
    ],
    () => {
      updateHighlightStylesFn.value?.()
    }
)

watch(
    () => payloadStore.highOrderLayoutMode,
    () => {
      const data = payloadStore.payload || payload.value
      if (!data) return
      render(data)
    }
)

// let rafPending = false
//
// watch(
//     () => regionStore.regions["global"]?.highlightNodes,
//     () => {
//
//       if (rafPending) return
//       rafPending = true
//
//       requestAnimationFrame(() => {
//         updateHighlightStylesFn.value?.()
//         rafPending = false
//       })
//
//     },
//     { deep: true }
// )


function edgeKey(d) {
  return `${d.source.id}→${d.target.id}`
}

function normalizeToken(x) {
  return String(x ?? "").trim().replace(/^['"]|['"]$/g, "").replace(/[']/g, "")
}

function getDisplayToken(token, legend) {
  const raw = String(token ?? "").trim()
  const tokenList = Array.isArray(legend?.tokens) ? legend.tokens : []
  const hit = tokenList.find(t => normalizeToken(t) === normalizeToken(raw))
  return hit || raw
}

function buildSemanticEdgeMap(classSeqs, firstSeqs) {
  const map = new Map()
  ;(classSeqs || []).forEach((classSeq, sid) => {
    const firstSeq = firstSeqs?.[sid] || []
    if (!Array.isArray(classSeq)) return
    for (let i = 0; i < classSeq.length - 1; i++) {
      const source = `node${classSeq[i]}`
      const target = `node${classSeq[i + 1]}`
      const key = `${source}→${target}`
      const appendEvent = normalizeToken(firstSeq[i + 1] ?? "")
      if (!appendEvent) continue
      if (!map.has(key)) map.set(key, { total: 0, events: new Map() })
      const entry = map.get(key)
      entry.total += 1
      entry.events.set(appendEvent, (entry.events.get(appendEvent) || 0) + 1)
    }
  })
  return map
}

function hasVisibleHighOrderStates(glyph, cls) {
  const g = glyph?.[String(cls)]
  if (!g) return false
  if (Array.isArray(g.full_order_states)) return g.full_order_states.length > 0
  return (g.unique_states || []).length > 0
}

// ------------------------
// 文件选择
// ------------------------
function onFileChange(e) {
  file.value = e.target.files[0]
  upload()
}

function triggerUpload() {
  fileInput.value.click()
}

// ------------------------
// 上传文件
// ------------------------
// async function upload() {
//   if (!file.value) return
//
//   const form = new FormData()
//   form.append("file", file.value)
//
//   const res = await fetch("http://localhost:8000/api/upload", {
//     method: "POST",
//     body: form
//   })
//
//   if (!res.ok) {
//     const err = await res.json()
//     alert(err.error || "Upload failed")
//     return
//   }
//
//   const data = await res.json()   // ✅ 直接用上传返回
//   payload.value = data
//
//   // ✅ 新增：写入全局 store
//   payloadStore.setPayload(data)
//   render(data)
// }

// ------------------------
// 上传 cluster.csv
// ------------------------

async function upload() {
  if (!file.value) return

  clusterFile.value = file.value

  const form = new FormData()
  form.append("cluster_file", file.value)

  form.append("K", 3)

  const res = await fetch(
      apiUrl("/api/rewrite"),
      {
        method: "POST",
        body: form
      }
  )

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const msg = err.detail ? `${err.error || "Rewrite failed"}: ${err.detail}` : (err.error || "Rewrite failed")
    alert(msg)
    return
  }


  const data = await res.json()

  payload.value = data
  payloadStore.setPayload(data, { setAsOriginal: true })
  render(data)
}
// ------------------------
// 渲染
// ------------------------
function render(data) {
  renderGraph(data)
}

function showTooltip(html, event) {
  const el = d3.select(tooltipRef.value)

  el.html(html)
      .style("left", event.clientX + 12 + "px")
      .style("top", event.clientY + 12 + "px")
      .style("opacity", 1)
}

function hideTooltip() {
  d3.select(tooltipRef.value)
      .style("opacity", 0)
}

// ⭐ 新增：处理图片点击
function handleSliceClick(event, nodeData) {
  // event.stopPropagation()

  // 获取点击位置
  const rect = svgRef.value.getBoundingClientRect()
  dialogX.value = event.clientX - rect.left + 220
  dialogY.value = event.clientY - rect.top + 20// 稍微向上偏移

  // 设置弹窗数据
  dialogNodeClass.value = nodeData.class
  inputNumber.value = null
  showDialog.value = true
}

// ⭐ 新增：处理确认按钮点击
async function handleDialogConfirm() {

  if (dialogNodeClass.value === null) return

  const form = new FormData()

  form.append("class_id", dialogNodeClass.value)
  form.append("new_K", inputNumber.value)

  form.append(
      "cluster_file",
      clusterFile.value   // ⭐这里
  )

  const res = await fetch(
      apiUrl("/api/refine_cluster"),
      {
        method: "POST",
        body: form
      }
  )

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    const msg = err.detail ? `${err.error || "Refine failed"}: ${err.detail}` : (err.error || "Refine failed")
    alert(msg)
    return
  }

  const data = await res.json()
  // 使用新图：节点已是 20、21，连线也连到 20、21；split_info 在 payload 里用于画「从 16 划分」的框
  payloadStore.setPayload(data, { setAsOriginal: false })
  closeDialog()
  render(data)
}

// ⭐ 新增：处理弹窗关闭
function closeDialog() {
  showDialog.value = false
  dialogNodeClass.value = null
  inputNumber.value = 0
}

/* ===============================
 * main render
 * =============================== */
function renderGraph(data) {
  let hoverNodeId = null
  let hoverEdgeKey = null

  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  svg.style("background-color", "transparent")

  const { graph, glyph, legend } = data

  const placeholder = legend.placeholder
  const tokens = legend.tokens.filter(t => t !== placeholder)

  // const color = buildColorScale(tokens)
  // renderLegend(legendRef.value, tokens, color)
  payloadStore.buildGlobalColorScale(tokens)
  const color = payloadStore.colorScale

  const rect = svgRef.value.getBoundingClientRect();
  const width = rect.width
  const height = rect.height

  // zoom 容器
  const root = svg.append("g").attr("class", "root")
  const zoom = d3.zoom()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => {
        root.attr("transform", event.transform)
      })

  svg.call(zoom)

  // ⭐ 初始缩放 1:1，不平移（布局中心已在 width/2, height/2）
  svg.call(zoom.transform, d3.zoomIdentity)

  // 复制数据（d3-force 会改对象）
  const nodes = graph.nodes
      .filter(d => hasVisibleHighOrderStates(glyph, d.class))
      .map(d => ({ ...d }))
  const visibleNodeIds = new Set(nodes.map(d => String(d.id)))
  if (nodes.length === 0) {
    svg.append("text")
        .attr("x", width / 2)
        .attr("y", height / 2)
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "middle")
        .attr("fill", "var(--text-muted)")
        .style("font-size", "12px")
        .text("No full-order high-order states in this view.")
    return
  }
  const links = graph.links
      .filter(l => {
        const sid = typeof l.source === "object" ? l.source.id : l.source
        const tid = typeof l.target === "object" ? l.target.id : l.target
        return visibleNodeIds.has(String(sid)) && visibleNodeIds.has(String(tid))
      })
      .map(d => ({ ...d }))

  // ⭐ 预计算 edge key
  links.forEach(l => {
    const sid = typeof l.source === "object" ? l.source.id : l.source
    const tid = typeof l.target === "object" ? l.target.id : l.target
    l._key = `${sid}→${tid}`
  })

  const semanticEdgeMap = buildSemanticEdgeMap(data.raw_sequences, data.first_order_sequences)
  links.forEach(l => {
    const entry = semanticEdgeMap.get(l._key)
    const events = Array.from(entry?.events?.entries?.() || [])
        .map(([eventName, support]) => ({
          eventName,
          label: getDisplayToken(eventName, legend),
          support,
          probability: entry?.total ? support / entry.total : 0
        }))
        .sort((a, b) => b.support - a.support || a.label.localeCompare(b.label))
    l.appendEvents = events
    l.primaryAppendEvent = events[0]?.eventName ?? null
  })

  // ===============================
  // compute entropy per node (Graph)
  // ===============================

  // 1) 建立 nodeId -> outgoing links 映射
  const outMap = new Map()

  links.forEach(l => {
    const sid = typeof l.source === "object" ? l.source.id : l.source
    if (!outMap.has(sid)) outMap.set(sid, [])
    outMap.get(sid).push(l)
  })

  // 1b) 建立 nodeId -> incoming links 映射
  const inMap = new Map()

  links.forEach(l => {
    const tid = typeof l.target === "object" ? l.target.id : l.target
    if (!inMap.has(tid)) inMap.set(tid, [])
    inMap.get(tid).push(l)
  })

  // 3) compute per node
  nodes.forEach(n => {
    const outLs = outMap.get(n.id) || []
    const inLs  = inMap.get(n.id)  || []

    n.outFlow = d3.sum(outLs, d => d.value)
    n.inFlow  = d3.sum(inLs,  d => d.value)
    n.entropy = entropyFromLinks(outLs)
  })

  // 建立熵到颜色的映射
  const entropies = nodes.map(d => d.entropy)
  const maxEntropy = d3.max(entropies) || 1

  const entropyColor = d3.scaleSequential(d3.interpolateYlOrRd)
      .domain([0, maxEntropy])

  const values = links.map(d => d.value)

  const minV = d3.min(values)
  const maxV = d3.max(values)

  const linkGray = d3.scalePow()
      .exponent(0.8)   // ⭐ 越小越陡 (0.2 ~ 0.5 推荐)
      .domain([minV, maxV])
      .range(["#eeeeee", "#444444"])
      .clamp(true)

  const linkOpacity = d3.scalePow()
      .exponent(0.6)
      .domain([minV, maxV])
      .range([0.2, 1])
      .clamp(true)

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

  const fullRawSeqs = payloadStore.payload?.raw_sequences || data.raw_sequences || []

  // 过滤前来源：以“当前选中的 region”为准（apply 后写入 sourceRegionId；apply 前 RegionPanel 会提前写入）
  const targetRid = regionStore.activeRegionId || "global"
  const targetRegion = regionStore.regions[targetRid]
  const previewObj = brushStore.preview?.value ?? brushStore.preview

  const effectiveSourceRid =
      targetRegion?.sourceRegionId ??
      previewObj?.sourceRid ??
      "global"

  let beforeSequences = []
  if (!effectiveSourceRid || effectiveSourceRid === "global") {
    beforeSequences = fullRawSeqs
  } else {
    const sourceRegion = regionStore.regions[effectiveSourceRid]
    if (Array.isArray(sourceRegion?.sequences) && sourceRegion.sequences.length > 0) {
      beforeSequences = sourceRegion.sequences
    } else if (Array.isArray(sourceRegion?.baseRawSeqs) && sourceRegion.baseRawSeqs.length > 0) {
      beforeSequences = sourceRegion.baseRawSeqs
    } else if (Array.isArray(sourceRegion?.sequenceIds) && sourceRegion.sequenceIds.length > 0) {
      beforeSequences = sourceRegion.sequenceIds
          .map(i => fullRawSeqs[i])
          .filter(Boolean)
    }
  }
  // 兜底：避免过滤前为空导致差分失效
  if (!Array.isArray(beforeSequences) || beforeSequences.length === 0) {
    beforeSequences = fullRawSeqs
  }

  let afterSequences = fullRawSeqs
  if (Array.isArray(brushStore.preview?.seqIds) && brushStore.preview.seqIds.length > 0) {
    afterSequences = brushStore.preview.seqIds
        .map(i => fullRawSeqs[i])
        .filter(Boolean)
  }

  const edgeCountBefore = buildEdgeCountFromSeqs(beforeSequences)
  const edgeCountAfter = buildEdgeCountFromSeqs(afterSequences)

  linkGrayRef.value = linkGray   // ✅ 新增

  // 分组框层放在最底下，避免挡住边的悬浮/点击
  const groupLayer = root.append("g").attr("class", "group-layer")

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
        return sid === tid ? 2 : 0
      })
      .attr("stroke-linecap", "round")
      .attr("opacity", d => linkOpacity(d.value))

  // 建索引：edgeKey -> DOM 元素（高亮更新用，避免每次扫全量 linkSel）
  const linkElByKey = new Map()
  linkSel.each(function(d) {
    linkElByKey.set(edgeKey(d), this)
  })

  linkSel
      .on("mouseenter", function(event, d) {
        d3.select(this).style("cursor", "pointer")

        showTooltip(
            `${d.source.class} → ${d.target.class}<br/>Next event: ${d.appendEvents?.[0]?.label ?? "n/a"}<br/>support: ${d.value}<br/>probability: ${d.appendEvents?.[0]?.probability != null ? (d.appendEvents[0].probability * 100).toFixed(2) + "%" : "n/a"}`, event)
      })
      .on("mouseleave", function() {
        hideTooltip()
      })
      .on("click", (event, d) => {
        event.stopPropagation()
        // 说明我现在在对全量图进行brush
        if (brushStore.interactionMode !== "brush") return

        brushStore.setActivePanelRegion(
            "global",
            "global"
        )

        if (!brushStore.activeBrushId) brushStore.createBrush()
        if (!brushStore.canEditActiveBrushFromRegion("global")) return

        const key = edgeKey(d)

        brushStore.toggleEdge(
            brushStore.activeBrushId,
            key
        )
      })

  linkSelRef.value = linkSel

  const nodeSel = root.append("g")
      .selectAll("g")
      .data(nodes)
      .enter()
      .append("g")
      .attr("class", "node")
      .call(
          d3.drag()
              .on("start", dragstarted)
              .on("drag", dragged)
              .on("end", dragended)
      )

  nodeSelRef.value = nodeSel

  // 回退按钮的点击层：放在最顶层，只放透明可点区域，避免被边挡住
  const revertHitLayer = root.append("g").attr("class", "revert-hit-layer")

  nodeSel
      .on("mouseenter", function(event, d) {
        d3.select(this).style("cursor", "pointer")
        d3.select(this).select("image").style("opacity", 1)

        // linkSel.attr("opacity", l =>
        //     l.source.id === d.id || l.target.id === d.id ? 1 : 0.05
        // )

        hoverNodeId = d.id
        hoverEdgeKey = null

        updateHighlightStylesFn.value?.()

        const outDeg = outMap.get(d.id)?.length || 0
        const inDeg  = inMap.get(d.id)?.length || 0

        showTooltip(
            `
      class: ${d.class}<br/>
<!--      entropy: ${d.entropy.toFixed(3)}<br/>-->
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
        d3.select(this).select("image").style("opacity", 0)

        // linkSel.attr("opacity", l => linkOpacity(l.value))
        hideTooltip()
      })
      .on("click", (event, d) => {

        event.stopPropagation()
	        payloadStore.toggleHighOrderClass(String(d.class), "global")
        if (brushStore.interactionMode === "brush") {
          brushStore.setActivePanelRegion("global", "global")
          if (!brushStore.activeBrushId) brushStore.createBrush()
          if (!brushStore.canEditActiveBrushFromRegion("global")) return
          brushStore.addClass(String(d.class))
        }
      })


  const NODE_W = 60
  const NODE_H = 25

  nodeSel.append("rect")
      .attr("x", -NODE_W/2)
      .attr("y", -NODE_H/2)
      .attr("width", NODE_W)
      .attr("height", NODE_H)
      .attr("rx", 6)
      .attr("fill", "#f5f5f5")
      .attr("stroke", d => entropyColor(d.entropy))
      .attr("stroke-width", d => 0.9 + d.entropy * 1.4)

  // 建索引：nodeId -> rect DOM 元素（高亮更新用）
  const nodeRectElById = new Map()
  nodeSel.each(function(d) {
    const rect = d3.select(this).select("rect").node()
    if (rect) nodeRectElById.set(d.id, rect)
  })

  // 节点旁边的文字
  nodeSel.append("text")
      .attr("x", -NODE_W/2 - 4)
      .attr("y", 0)
      .attr("text-anchor", "end")
      .attr("dominant-baseline", "middle")
      .style("font-size", "11px")
      .text(d => `${d.class}`)

  // ⭐ 新增：添加slice图标到每个节点
  nodeSel.append("image")
      .attr("x", NODE_W/2 - 6)  // 放在右上角
      .attr("y", -NODE_H/2 - 6)   // 稍微超出节点顶部
      .attr("width", 12)
      .attr("height", 12)
      .attr("href", sliceIcon)
      .style("cursor", "pointer")
      .style("opacity", 0)  // 默认隐藏
      // 允许点到图标本身，触发 handleSliceClick 弹窗
      .style("pointer-events", "all")
      .style("transition", "opacity 0.2s")
      .on("mouseenter", function(event) {
        d3.select(this).style("opacity", 1)
      })
      .on("mouseleave", function(event) {
        d3.select(this).style("opacity", 0)
      })
      .on("click", function(event, d) {
        // 防止点击图标后触发节点本身的 click（例如切 class / brush）
        event.stopPropagation()
        handleSliceClick(event, d)
      })

  // glyph（每个节点一个 glyph；split_info 用于画分组框，不在这里处理）
  drawGlyphForce(nodeSel, glyph, tokens, color, NODE_W, NODE_H)

  const layerMap = computeLayerMap(data.raw_sequences)
  const maxLayer = d3.max(nodes, d => layerMap.get(String(d.class)) ?? 0) || 1
  const nodeById = new Map(nodes.map(n => [n.id, n]))

  function getId(x) {
    return typeof x === "object" ? x.id : x
  }

  const useLayeredLayout = payloadStore.highOrderLayoutMode === "layered"
  if (useLayeredLayout) {
    applyLayeredLayout(nodes, links, {
      nodeW: NODE_W * 0.62,
      nodeH: NODE_H,
      ranksep: 18,
      nodesep: 14,
    })
  } else {
    /* ===============================
    * ForceAtlas2 布局（Gephi style）
    * =============================== */
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
          weight: 1 / (l.value ?? 1)
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
    scalingRatio: 2000 * (20/nodes.length),  // 10 ❌ 太大导致过于分散
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

  /* -------------------------------
   * 同一 split 组内的节点聚拢，避免框框包住中间其它节点
   * ------------------------------- */
  const splitInfo = data.split_info || {}
  const gap = 10
  const splitGroupNodeIds = new Set()
  const clusterBboxes = []

  Object.keys(splitInfo).forEach(parentClass => {
    const childClasses = Object.keys(splitInfo[parentClass]).map(c => String(c))
    const groupNodes = nodes.filter(n => childClasses.includes(String(n.class)))
    groupNodes.forEach(n => splitGroupNodeIds.add(n.id))
    if (groupNodes.length <= 1) return
    const cx = d3.mean(groupNodes, n => n.x)
    const cy = d3.mean(groupNodes, n => n.y)
    const totalW = (groupNodes.length - 1) * (NODE_W + gap)
    groupNodes.forEach((n, i) => {
      n.x = cx - totalW / 2 + i * (NODE_W + gap) + NODE_W / 2
      n.y = cy
    })
    const pad = NODE_W * 0.6
    clusterBboxes.push({
      minX: cx - totalW / 2 - NODE_W / 2 - pad,
      minY: cy - NODE_H / 2 - pad,
      maxX: cx + totalW / 2 + NODE_W / 2 + pad,
      maxY: cy + NODE_H / 2 + pad
    })
  })

  const connectedToSplit = new Set()

  links.forEach(l => {

    const sid = typeof l.source === "object" ? l.source.id : l.source
    const tid = typeof l.target === "object" ? l.target.id : l.target

    if (splitGroupNodeIds.has(sid)) {
      connectedToSplit.add(tid)
    }

    if (splitGroupNodeIds.has(tid)) {
      connectedToSplit.add(sid)
    }

  })

  splitGroupNodeIds.forEach(id => connectedToSplit.add(id))

  /* -------------------------------
   * 把与 split 簇重叠的其它节点推开，避免叠在一起
   * ------------------------------- */
  const nodeHalfW = NODE_W / 2
  const nodeHalfH = NODE_H / 2
  for (let iter = 0; iter < 5; iter++) {
    nodes.forEach(n => {
      if (splitGroupNodeIds.has(n.id)) return
      if (connectedToSplit.has(n.id)) return
      clusterBboxes.forEach(bbox => {
        const nx = n.x
        const ny = n.y
        const nMinX = nx - nodeHalfW
        const nMaxX = nx + nodeHalfW
        const nMinY = ny - nodeHalfH
        const nMaxY = ny + nodeHalfH
        const overlapLeft = nMaxX - bbox.minX
        const overlapRight = bbox.maxX - nMinX
        const overlapTop = nMaxY - bbox.minY
        const overlapBottom = bbox.maxY - nMinY
        if (overlapLeft <= 0 || overlapRight <= 0 || overlapTop <= 0 || overlapBottom <= 0) return
        const pushX = overlapLeft <= overlapRight ? overlapLeft : -overlapRight
        const pushY = overlapTop <= overlapBottom ? overlapTop : -overlapBottom
        if (Math.abs(pushX) <= Math.abs(pushY)) {
          n.x += pushX
        } else {
          n.y += pushY
        }
      })
    })
  }

  // 全局去重叠：对所有节点做矩形碰撞松弛，避免 FA2 后仍有节点重叠
  function resolveNodeOverlaps(allNodes, padX = 6, padY = 4, iterations = 60) {
    const halfW = NODE_W / 2
    const halfH = NODE_H / 2
    for (let it = 0; it < iterations; it++) {
      let moved = false
      for (let i = 0; i < allNodes.length; i++) {
        for (let j = i + 1; j < allNodes.length; j++) {
          const a = allNodes[i]
          const b = allNodes[j]
          const dx = b.x - a.x
          const dy = b.y - a.y
          const minDx = halfW * 2 + padX
          const minDy = halfH * 2 + padY
          const overlapX = minDx - Math.abs(dx)
          const overlapY = minDy - Math.abs(dy)
          if (overlapX <= 0 || overlapY <= 0) continue

          // 沿重叠更小的轴分离，减少布局抖动
          if (overlapX < overlapY) {
            const sign = dx >= 0 ? 1 : -1
            const push = overlapX / 2
            a.x -= sign * push
            b.x += sign * push
          } else {
            const sign = dy >= 0 ? 1 : -1
            const push = overlapY / 2
            a.y -= sign * push
            b.y += sign * push
          }
          moved = true
        }
      }
      if (!moved) break
    }
  }

  resolveNodeOverlaps(nodes, 8, 6, 80)

  /* -------------------------------
   * 写回 link
   * ------------------------------- */

  links.forEach(l => {

    l.source = nodeById.get(getId(l.source))
    l.target = nodeById.get(getId(l.target))

  })

  function getX(n) { return n.fx != null ? n.fx : n.x }
  function getY(n) { return n.fy != null ? n.fy : n.y }

  function updateGroupBoxes() {
    groupLayer.selectAll("*").remove()
    revertHitLayer.selectAll("*").remove()
    const splitInfo = data.split_info || {}
    const parentClasses = Object.keys(splitInfo)
    if (parentClasses.length === 0) return
    parentClasses.forEach(parentClass => {
      const childClasses = Object.keys(splitInfo[parentClass]).map(c => String(c))
      const nodesInGroup = nodes.filter(n => childClasses.includes(String(n.class)))
      if (nodesInGroup.length === 0) return
      const pad = 14
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      nodesInGroup.forEach(n => {
        const x = getX(n), y = getY(n)
        minX = Math.min(minX, x - NODE_W / 2 - pad - 10)
        minY = Math.min(minY, y - NODE_H / 2 - pad)
        maxX = Math.max(maxX, x + NODE_W / 2 + pad)
        maxY = Math.max(maxY, y + NODE_H / 2 + pad)
      })
      groupLayer.append("rect")
          .attr("x", minX)
          .attr("y", minY)
          .attr("width", maxX - minX)
          .attr("height", maxY - minY)
          .attr("rx", 8)
          .attr("fill", "rgba(200,220,255,0.2)")
          .attr("stroke", "#669")
          .attr("stroke-width", 1.5)
          .attr("stroke-dasharray", "5,3")
          // 大框不参与命中，避免挡住下层节点/边的悬浮
          .attr("pointer-events", "none")

      // 顶层透明点击区域：放在框上方，避免盖住子节点导致节点 hover 失效
      if (payloadStore.originalPayload) {
        const hitW = 72
        const hitH = 18
        const labelY = minY - 4
        revertHitLayer.append("rect")
            .attr("x", minX + 4)
            .attr("y", labelY - hitH + 4)
            .attr("width", hitW)
            .attr("height", hitH)
            .attr("rx", 4)
            .attr("fill", "transparent")
            .style("cursor", "pointer")
            .on("click", (event) => {
              // event.stopPropagation()
              payloadStore.resetToOriginal()
              if (payloadStore.payload) render(payloadStore.payload)
            })

        revertHitLayer.append("text")
            .attr("x", minX + 8)
            .attr("y", labelY)
            .attr("font-size", 11)
            .attr("fill", "#556")
            .attr("pointer-events", "none")
            .text(`← ${parentClass}`)
      }
    })
  }

  function refreshPositions() {
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
    updateGroupBoxes()
  }
  refreshPositions()

  // 保存全局图节点坐标（用于 ForceGraph 子图复用相对布局）
  const posById = {}
  let minX2 = Infinity
  let maxX2 = -Infinity
  let minY2 = Infinity
  let maxY2 = -Infinity
  nodes.forEach(n => {
    const key = String(n.id)
    posById[key] = { x: n.x, y: n.y }
    if (Number.isFinite(n.x)) {
      minX2 = Math.min(minX2, n.x)
      maxX2 = Math.max(maxX2, n.x)
    }
    if (Number.isFinite(n.y)) {
      minY2 = Math.min(minY2, n.y)
      maxY2 = Math.max(maxY2, n.y)
    }
  })
  payloadStore.setGlobalGraphNodePositions(
      posById,
      {
        minX: Number.isFinite(minX2) ? minX2 : 0,
        maxX: Number.isFinite(maxX2) ? maxX2 : 0,
        minY: Number.isFinite(minY2) ? minY2 : 0,
        maxY: Number.isFinite(maxY2) ? maxY2 : 0,
      }
  )

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
    // 维护全局布局坐标（用于子图复用/对齐）
    payloadStore.updateGlobalGraphNodePosition(d.id, d.x, d.y)
    d3.select(event.sourceEvent?.target)?.style("cursor", null)
  }


  function updateHighlightStyles() {


    // GraphGlyph 自己的高亮数据来自你“在哪张图上刷”的 sourceRid。
    // 目前这里仍以 global 图本身的高亮集合为准（brush 在全局图上交互时写入 global）。
    const r = regionStore.regions["global"]

    const highlightNodes = r?.highlightNodes ?? new Set()
    const highlightEdges = r?.highlightEdges ?? new Set()

    const hasHighlight =
        highlightNodes.size > 0 ||
        highlightEdges.size > 0
    const hasEdgeHighlight = highlightEdges.size > 0

    const active = brushStore.activeBrush

    // 差分的“过滤前来源 brush”应当取当前 active region（目标 region）上保存的 sourceBrushId
    const targetRid = regionStore.activeRegionId || "global"
    const targetRegion = regionStore.regions[targetRid]

    const sourceBrushId =
        targetRegion?.sourceBrushId ??
        (targetRegion?.sourceRegionId
            ? (regionStore.regions[targetRegion.sourceRegionId]?.brushId ?? null)
            : null)

    const sourceBrushColor =
        sourceBrushId && sourceBrushId !== "global"
            ? (brushStore.brushes?.[sourceBrushId]?.color || "#444444")
            : "#444444"

    // diffOpacity：用 |before-after| 反映差值大小（透明度只看绝对值）
    let maxAbsDiff = 0
    let minAbsDiff = Infinity  // 或者用一个很大的数
    const allEdgeKeys = new Set([
      ...edgeCountBefore.keys(),
      ...edgeCountAfter.keys()
    ])
    allEdgeKeys.forEach((k) => {
      const absDiff = Math.abs((edgeCountBefore.get(k) || 0) - (edgeCountAfter.get(k) || 0))
      if (absDiff > maxAbsDiff) maxAbsDiff = absDiff
      if (absDiff < minAbsDiff) minAbsDiff = absDiff
    })
    const diffOpacity = d3.scalePow()
        .exponent(0.5)
        .domain([minAbsDiff, maxAbsDiff || 1])
        .range([0.1, 1])
        .clamp(true)

    const getBefore = (k) => edgeCountBefore.get(k) || 0
    const getAfter = (k) => edgeCountAfter.get(k) || 0
    const getDiff = (k) => getAfter(k) - getBefore(k)
    const getAbsDiff = (k) => Math.abs(getDiff(k))
    const activeAppendEvent = payloadStore.hoveredAppendEvent || payloadStore.focusedAppendEvent
    const hoveredHighOrderClasses = new Set(payloadStore.hoveredHighOrderClasses || [])

    const edgeHasAppendEvent = (d, eventName) => {
      if (!eventName) return false
      return (d.appendEvents || []).some(evt => normalizeToken(evt.eventName) === normalizeToken(eventName))
    }

    const edgeMatchesContextMap = (d) => {
      if (activeAppendEvent) return edgeHasAppendEvent(d, activeAppendEvent)
      return false
    }

    const pickHighlightColor = (k, fallback) => {
      let baseColor = null
      const before = getBefore(k)
      const after = getAfter(k)

      // 哪个数据更大就用谁的颜色：刷后(after)大 -> 当前刷子色；刷前(before)大 -> 来源刷子色
      if (after > before && active?.color) baseColor = active.color
      if (before >= after && sourceBrushColor) baseColor = sourceBrushColor
      // 相等时优先来源色；无来源色再退当前色
      if (!baseColor && sourceBrushColor) baseColor = sourceBrushColor
      if (!baseColor && active?.color) baseColor = active.color

      if (!baseColor) return fallback

      const lightBrushColor = baseColor
          ? d3.hsl(baseColor).brighter(1.1).formatRgb() // 1.5 表示变亮程度，可以根据需要调整
          : "#eeeeee";

      const darkBrushColor = baseColor

      const diffColor = d3.scalePow()
          .exponent(0.8)
          .domain([minAbsDiff, maxAbsDiff || 1])
          .range([lightBrushColor, darkBrushColor])
          .clamp(true)

      return diffColor(getAbsDiff(k))
    }


    nodeSel.select("rect")
        .attr("stroke", d => {
          if (hoveredHighOrderClasses.size > 0) {
            return hoveredHighOrderClasses.has(String(d.class)) ? "#111827" : "#aaa"
          }
          if (!active) return entropyColor(d.entropy)
          if (!highlightNodes) return entropyColor(d.entropy)
          const hit = highlightNodes.has(d.id)
          return hit ? active.color : entropyColor(d.entropy)
        })
        .attr("stroke-width", d => {
          if (hoveredHighOrderClasses.size > 0) {
            return hoveredHighOrderClasses.has(String(d.class)) ? 2 : 1
          }
          if (!active) return 0.9 + d.entropy * 1.4
          return highlightNodes.has(d.id) ? 1.5 : 0.9 + d.entropy * 1.4
        })
        .attr("opacity", d => {
          if (hoveredHighOrderClasses.size > 0) {
            return hoveredHighOrderClasses.has(String(d.class)) ? 1 : 0.22
          }
          return 1
        })

    // 边
    linkSel
        .attr("opacity", d => {
          const k = edgeKey(d)
          if (activeAppendEvent) {
            return edgeMatchesContextMap(d) ? 1 : 0.04
          }
          if (hoveredHighOrderClasses.size > 0) {
            return linkOpacity(d.value)
          }
          // highlight 优先
          if (hasEdgeHighlight) {
            if (!highlightEdges.has(k)) return 0.01
            return diffOpacity(getAbsDiff(k))
          }
          // hover 次优先
          if (hoverNodeId) {
            if (
                d.source.id === hoverNodeId ||
                d.target.id === hoverNodeId
            ) return 1
            return 0.01
          }

          if (hoverEdgeKey) {
            return k === hoverEdgeKey ? 1 : 0.01
          }
          // default
          return linkOpacity(d.value)
        })
        .attr("fill", d => {
          const sid = d.source
          const tid = d.target
          if (activeAppendEvent && edgeMatchesContextMap(d)) {
            const evt = activeAppendEvent || d.primaryAppendEvent
            return sid !== tid ? (evt ? color(getDisplayToken(evt, legend)) : linkGray(d.value)) : "none"
          }
          if (!hasEdgeHighlight) return sid !== tid ? linkGray(d.value) : "none"
          const k = edgeKey(d)
          if (highlightEdges.has(k)) {
            return sid !== tid ? pickHighlightColor(k, linkGray(d.value)) : "none"
          }
          return sid !== tid ? linkGray(d.value) : "none"
        })
        .attr("stroke", d => {
          const sid = d.source
          const tid = d.target
          if (activeAppendEvent && edgeMatchesContextMap(d)) {
            const evt = activeAppendEvent || d.primaryAppendEvent
            return sid === tid ? (evt ? color(getDisplayToken(evt, legend)) : linkGray(d.value)) : "none"
          }
          if (!hasEdgeHighlight) return sid === tid ? linkGray(d.value) : "none"
          const k = edgeKey(d)
          if (highlightEdges.has(k)) {
            return sid === tid ? pickHighlightColor(k, linkGray(d.value)) : "none"
          }
          return sid === tid ? linkGray(d.value) : "none"
        })
  }
  // ⭐ 注册到组件级 ref
  updateHighlightStylesFn.value = updateHighlightStyles
}

</script>

<template>
  <!-- 新增的弹窗模板 -->
  <Teleport to="body">
    <div v-if="showDialog"
         class="slice-dialog"
         :style="{
           position: 'fixed',
           left: dialogX + 'px',
           top: dialogY + 'px',
           background: 'white',
           border: '1px solid #ccc',
           borderRadius: '8px',
           padding: '16px',
           boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
           zIndex: 1000,
           minWidth: '20px',
           height: '40px'
         }">
      <!-- 右上角的图标按钮 -->
      <div style="position: absolute; top: 8px; right: 8px; display: flex; gap: 4px;">
        <img
            src="../assets/confirm.png"
            @click="handleDialogConfirm"
            style="width: 15px; height: 15px; cursor: pointer; opacity: 1; transition: opacity 0.2s;"
            @mouseenter="e => e.target.style.opacity = 1"
            @mouseleave="e => e.target.style.opacity = 0.7"
        />
        <img
            src="../assets/delete.png"
            @click="closeDialog"
            style="width: 16px; height: 16px; cursor: pointer; opacity: 1; transition: opacity 0.2s;"
            @mouseenter="e => e.target.style.opacity = 1"
            @mouseleave="e => e.target.style.opacity = 0.7"
        />
      </div>
      <div style="margin-top: 6px; margin-bottom: 0; font-weight: bold; font-size: 12px">
        Node: {{ dialogNodeClass }}
      </div>
      <input
          type="number"
          v-model.number="inputNumber"
          style="width: 50px; padding: 0; margin-bottom: 4px;margin-left: 0px; border: 1px solid #ddd; border-radius: 4px;height: 20px"
          placeholder=""
      />
    </div>
  </Teleport>

  <!-- 点击弹窗外区域关闭的遮罩 -->
  <div v-if="showDialog"
       style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; z-index: 999; pointer-events: none;"
       @click="closeDialog">
  </div>

  <div class="graph-container">
    <div class="graph-header"
         @click="regionStore.setActive('global')">
      <div class="control">
	        <input ref="fileInput" type="file" accept=".csv" class="hidden-file-input" @change="onFileChange" />
	        <el-icon :size="10" @click="triggerUpload" class="upload-btn"><Upload /></el-icon>
	        <span class="global-title">HIGHER-ORDER NETWORK</span>
	        <div class="layout-toggle" title="Switch graph layout" @click.stop>
	          <button
	              :class="{ active: payloadStore.highOrderLayoutMode === 'force' }"
	              @click="payloadStore.setHighOrderLayoutMode('force')"
	          >
	            Force
	          </button>
	          <button
	              :class="{ active: payloadStore.highOrderLayoutMode === 'layered' }"
	              @click="payloadStore.setHighOrderLayoutMode('layered')"
	          >
	            Layered
	          </button>
	        </div>
	      </div>
	    </div>

    <div class="sankey-content">
      <!-- 只有一个.svg-section，内部包含图例和SVG -->
      <div class="svg-section">
        <!-- 提示框 -->
        <div ref="tooltipRef" class="tooltip"></div>
        <!-- SVG -->
        <svg ref="svgRef"
             style="background-color: transparent; border: none;"
        ></svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0px;
  background: var(--panel-bg);
  box-sizing: border-box;
}

.sankey-content {
  flex: 1;
  display: flex;
  gap: 16px;
  min-height: 0; /* 重要：防止内容溢出 */
}

.legend-section {
  width: 220px;
  flex-shrink: 0;
  overflow-y: auto;
}

.svg-section {
  flex: 1;
  position: relative;
  min-width: 0;
  min-height: 0;
  /*overflow: auto; 添加滚动条查看完整SVG */
}

.node rect {
  cursor: default;
}

.link {
  pointer-events: none;
}

.tooltip {
  position: fixed;
  pointer-events: none;
  background: rgba(255, 255, 255, 0.96);
  color: var(--text-main);
  border: 1px solid var(--panel-border);
  box-shadow: var(--shadow-soft);
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

.svg-section svg {
  width: 100%;
  height: 100%;
  display: block;
  border: none;
  border-top: 1px solid var(--panel-border);
  border-radius: 0;
  background-color: #ffffff;
}

/* 文件输入样式 */
.control input[type="file"] {
  padding: 6px 12px;
  border: 1px solid var(--panel-border);
  border-radius: 4px;
  background-color: var(--panel-soft);
  font-size: 12px;
  cursor: pointer;
}

.control input[type="file"]:hover {
  border-color: var(--accent);
  background-color: var(--accent-soft);
}

.graph-header {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  background: linear-gradient(180deg, #fbfcfe, #f2f5f8);
}

.graph-header {
  justify-content: flex-start;
  border-bottom: 1px solid var(--panel-border);
  padding: 6px 8px 4px;
}

.control {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
}

.global-title {
  color: var(--text-main);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}

.layout-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: 6px;
  padding: 1px;
  border: 1px solid var(--panel-border);
  border-radius: 5px;
  background: #fff;
}

.layout-toggle button {
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 10px;
  line-height: 1;
  padding: 4px 6px;
}

.layout-toggle button.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}

/* 文件上传样式 */
.hidden-file-input {
  display: none;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  margin-left: 0;
  margin-top: 0;
  border-radius: 6px;
  cursor: pointer;
  background: #fff;
  color: var(--text-muted);
  border: 1px solid var(--panel-border);
  transition: all 0.2s ease;
}

.upload-btn:hover {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: rgba(47, 111, 159, 0.45);
}


.upload-btn:active {
  transform: scale(0.97);
}

</style>

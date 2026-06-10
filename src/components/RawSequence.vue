<script setup>
import {
  ref, watch, computed
} from "vue"
import * as d3 from "d3"
import { usePayloadStore } from "@/store/payloadStore.js"
import {
  canonicalJsonKey,
  honvisEntropyFromLinks,
  computeLayerMap,
  selfLoopTaperedPath,
  curvedTaperedLinkPath
} from "./tool.js"
import {sankey, sankeyLinkHorizontal} from "d3-sankey";
import { useRegionStore } from "@/store/regionStore.js"
import { useBrushStore } from "@/store/brushStore.js"
import Graph from "graphology"
import forceAtlas2 from "graphology-layout-forceatlas2"

/* ===============================
 * refs & store
 * =============================== */
const payloadStore = usePayloadStore()
const regionStore = useRegionStore()
const brushStore = useBrushStore()

// 每次渲染时取当前 colorScale，避免未初始化时为 null 导致 color is not a function
function getColor() {
  const scale = payloadStore.colorScale
  if (typeof scale === "function") return scale
  return () => "#999"
}

// 用 token 查色时优先匹配全局 domain，避免 d3 ordinal 对未知值自动扩域导致颜色漂移
function getTokenColor(token, color) {
  const raw = String(token ?? "").trim()
  const domain = typeof color?.domain === "function"
      ? new Set(color.domain().map(d => String(d).trim()))
      : null

  const candidates = [
    raw,
    raw.replace(/^['"]|['"]$/g, ""), // 去掉首尾引号
    raw.replace(/[']/g, ""),          // 去掉单引号
    raw.replace(/[()']/g, "").trim()  // 兼容历史清洗
  ]

  if (domain) {
    for (const k of candidates) {
      if (k && domain.has(k)) return color(k)
    }
    return "#999"
  }

  const c = color(raw)
  return c ?? "#999"
}

function normalizeTokenForMatch(x) {
  return String(x ?? "")
      .trim()
      .toUpperCase()
      .replace(/^['"]|['"]$/g, "")
      .replace(/[']/g, "")
      .replace(/[()]/g, "")
      .replace(/\s+/g, "")
}

// Tooltip/文本显示时尽量还原到 legend 里的原始 token（例如 Attempt(Miss)）
function getDisplayToken(token, legend) {
  const raw = String(token ?? "").trim()
  const tokenList = Array.isArray(legend?.tokens) ? legend.tokens : []
  if (tokenList.includes(raw)) return raw

  const key = normalizeTokenForMatch(raw)
  const hit = tokenList.find(t => normalizeTokenForMatch(t) === key)
  return hit || raw
}
const svgRef = ref(null)
const tooltipRef = ref(null)
// 可视化模式：序列图 / 桑基图 / Graph(FA2)
const viewMode = ref("graph")   // "sequence" | "sankey" | "graph"
const isViewSelecting = ref(false)
const pendingRenderData = ref(null)

const sequenceData = computed(() => {

  const rid = regionStore.activeRegionId

  if (!rid) {
    return payloadStore.payload
  }

  const region = regionStore.regions[rid]

  if (!region) return payloadStore.payload

  const full = payloadStore.payload

  // ⭐ slice 开启时使用 region 的切片 first_order，与 Sequence.vue 的 region.sequences 一致
  if (region.sliceMode && region.slicedFirstOrderSequences?.length > 0) {
    return {
      ...full,
      raw_sequences: region.slicedFirstOrderSequences,
      first_order_sequences: region.slicedFirstOrderSequences,
      sequence_ids: region.slicedFirstOrderSequences.map((_, i) => i)
    }
  }

  if (!region.sequenceIds || region.sequenceIds.length === 0) {
    return payloadStore.payload
  }

  const ids = region.sequenceIds

  const raw = ids.map(i => full.raw_sequences[i])
  const first = ids.map(i => full.first_order_sequences[i])

  return {
    ...full,
    raw_sequences: raw,
    first_order_sequences: first,
    sequence_ids: ids
  }

})

/* ===============================
 * watch: keep consistent with force graph
 * =============================== */

function scheduleRender(data) {
  requestAnimationFrame(() => {
    renderByMode(data)
  })
}


function flushPendingRender() {
  if (pendingRenderData.value) {
    const data = pendingRenderData.value
    pendingRenderData.value = null
    scheduleRender(data)
  }
}

function onViewSelectPointerDown() {
  isViewSelecting.value = true
}

function onViewSelectChange() {
  isViewSelecting.value = false

  if (pendingRenderData.value) {
    renderByMode(pendingRenderData.value)
    pendingRenderData.value = null
  }
}

function onViewSelectBlur() {
  isViewSelecting.value = false
  flushPendingRender()
}

watch(
    () => [
      sequenceData.value,
      payloadStore.payload,
      payloadStore.colorScale,
      viewMode.value
    ],
    ([data]) => {

      if (!data) {
        d3.select(svgRef.value).selectAll("*").remove()
        return
      }

      // ⭐⭐关键：选择框展开时禁止 render
      if (isViewSelecting.value) {
        pendingRenderData.value = data
        return
      }

      renderByMode(data)
    },
    { flush: "post" }
)

function renderByMode(data) {
  if (!data) {
    d3.select(svgRef.value).selectAll("*").remove()
    return
  }

  if (viewMode.value === "sequence") {
    renderSequenceGraph(data)
  } else if (viewMode.value === "sankey") {
    renderSankeyGraph(data)
  } else if (viewMode.value === "graph") {
    renderFa2Graph(data)
  }
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

function moveTooltip(event) {
  const wrapper = svgRef.value?.parentElement   // .seq-view-wrapper
  if (!wrapper) return

  const rect = wrapper.getBoundingClientRect()
  const x = event.clientX - rect.left + wrapper.scrollLeft
  const y = event.clientY - rect.top + wrapper.scrollTop

  d3.select(tooltipRef.value)
      .style("left", x + 12 + "px")
      .style("top", y - 12 + "px")
}

function buildSankeyFromSequences(seqs) {

  const nodeMap = new Map()
  const linkMap = new Map()

  for (const seq of seqs) {

    for (let i = 0; i < seq.length; i++) {

      const cls = String(seq[i])
      const nodeId = `${cls}_${i}`   // ⭐ 加位置

      if (!nodeMap.has(nodeId)) {
        nodeMap.set(nodeId, {
          id: nodeId,
          token: cls,
          pos: i
        })
      }

      if (i < seq.length - 1) {

        const nextCls = String(seq[i + 1])
        const nextId = `${nextCls}_${i + 1}`

        const key = `${nodeId}→${nextId}`

        linkMap.set(
            key,
            (linkMap.get(key) || 0) + 1
        )
      }
    }
  }

  const nodes = Array.from(nodeMap.values())

  const links = Array.from(linkMap.entries()).map(([k, v]) => {

    const [s, t] = k.split("→")

    return {
      source: s,
      target: t,
      value: v
    }

  })

  return { nodes, links }
}

function renderSankeyGraph(data) {

  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const seqs = data.first_order_sequences

  if (!seqs || seqs.length === 0) return

  const sankeyData = buildSankeyFromSequences(seqs)

  renderSankey({
    sankey: sankeyData,
    glyph: data.glyph,
    legend: data.legend
  })

}

function renderSankey(data) {
  const { sankey: sankeyData, glyph, legend } = data
  const color = getColor()

  const linksBySource = d3.group(sankeyData.links, d => d.source)
  const linksByTarget = d3.group(sankeyData.links, d => d.target)

  const nodeInMap = {}
  const nodeOutMap = {}

  sankeyData.nodes.forEach(n => {
    const incoming = linksByTarget.get(n.id) || []
    const outgoing = linksBySource.get(n.id) || []

    nodeInMap[n.id] = d3.sum(incoming, l => +l.value || 0)
    nodeOutMap[n.id] = d3.sum(outgoing, l => +l.value || 0)
  })

  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const root = svg.append("g")
      .attr("class","root")
      .attr("transform", "translate(0,0)")   // ⭐ 明确初始状态

  // ==========================
  // (NEW) value 压缩：缩小极端差距
  // ==========================
  const COMPRESS_MODE = "sqrt"   // "sqrt" | "pow" | "log"
  const ALPHA = 1              // pow 模式才用：0.3~0.6（0.5=sqrt）

  // 取 links 的原始 value（更可靠，因为 node.value 通常由 link 决定）
  const rawLinkValues = sankeyData.links.map(l => +l.value || 0)
  const maxV = d3.max(rawLinkValues) || 1

  // 压缩函数：输入 raw value，输出显示用 value（给 sankey 用）
  const compressValue = (v) => {
    v = Math.max(0, +v || 0)
    if (COMPRESS_MODE === "sqrt") return Math.sqrt(v)
    if (COMPRESS_MODE === "pow")  return Math.pow(v, ALPHA)
    if (COMPRESS_MODE === "log")  return Math.log1p(v) // log(1+v), 避免 0 问题
    return v
  }

  // ===============================
  // GLOBAL node value (for height)
  // ===============================
  const nodeValueMap = {}
  sankeyData.nodes.forEach(n => {
    nodeValueMap[n.id] = compressValue(+n.value || 0)
  })

  const height = svgRef.value.parentElement.clientHeight || 600

  // —— glyph 固定参数（全局常数）——
  const GLYPH_R = 8           // 减小半径
  const GLYPH_GAP = 4         // 减小间隙
  const GLYPH_PADDING = 6
  const MIN_NODE_HEIGHT =
      4 * GLYPH_R +
      4 * GLYPH_PADDING + 10;   // ⭐ 给文本 / stroke / 误差余量

  const NODE_PADDING = 10   // 10~14 是非常常见的稳定区间

  // —— 从 glyph 数据中取最大阶数 ——
  const maxOrder = d3.max(
      Object.values(glyph),
      d => d.max_order
  )

  // —— glyph 横向占用宽度 ——
  const glyphWidth = 2

  const nodeWidth =
      glyphWidth + 2 * GLYPH_PADDING

  // —— 先 probe 一次 Sankey，获取 depth 信息 ——
  const probeSk = sankey()
      .nodeId(d => d.id)
      .nodeWidth(nodeWidth)
      .nodePadding(NODE_PADDING)
      .extent([[0, 0], [1000, height]])   // 临时宽度即可

  const probeGraph = {
    nodes: sankeyData.nodes.map(n => {
      // 同样计算原始流量
      const incoming = linksByTarget.get(n.id) || []
      const outgoing = linksBySource.get(n.id) || []
      const inSum = d3.sum(incoming, l => +l.value || 0)
      const outSum = d3.sum(outgoing, l => +l.value || 0)
      // const rawValue = Math.max(inSum, outSum)

      return {
        ...n,
        raw_value: nodeInMap[n.id],   // 用真实入度显示
        // raw_value: rawValue,
        // value: compressValue(rawValue)
      }
    }),
    links: sankeyData.links.map(l => ({
      ...l,
      raw_value: +l.value || 0,
      value: compressValue(+l.value || 0)
    }))
  }

  probeSk(probeGraph)

  const nodesByDepth = d3.group(probeGraph.nodes, d => d.depth)

  const maxNodesInColumn = d3.max(
      Array.from(nodesByDepth.values()),
      col => col.length
  )

  const minRequiredHeight =
      maxNodesInColumn * MIN_NODE_HEIGHT +
      (maxNodesInColumn - 1) * NODE_PADDING + 20

  const finalHeight = Math.max(
      minRequiredHeight,
      +svg.attr("height")/6
  )

  svg.attr("height", finalHeight)

  // Sankey 实际列数
  const numColumns =
      d3.max(probeGraph.nodes, d => d.depth) + 1

  const BASE_GAP = 90
  const MIN_GAP = 50

  const columnGap = Math.max(
      MIN_GAP,
      BASE_GAP
      // BASE_GAP * (numColumns / 15)
  )
  //
  // // 不同列节点之间的间距
  // const columnGap = 50
  const leftMargin = 20
  const rightMargin = 40

  const requiredWidth =
      leftMargin +
      numColumns * nodeWidth +
      (numColumns - 1) * columnGap +
      rightMargin

  // —— ⭐ 覆盖 SVG 宽度 ⭐ ——
  svg.attr("width", requiredWidth)
  svg.attr("height", finalHeight)

  const sk = sankey()
      .nodeId(d => d.id)
      .nodeWidth(nodeWidth)
      .nodePadding(NODE_PADDING)
      .nodeAlign(d => d.pos)
      .extent([
        [leftMargin, 10],
        [requiredWidth - rightMargin, finalHeight - 10]
      ])

  const graph = {
    nodes: sankeyData.nodes.map(n => {
      // 计算每个节点的原始流量
      const incoming = linksByTarget.get(n.id) || []
      const outgoing = linksBySource.get(n.id) || []
      const inSum = d3.sum(incoming, l => +l.value || 0)
      const outSum = d3.sum(outgoing, l => +l.value || 0)
      const rawValue = Math.max(inSum, outSum)

      return {
        ...n,
        raw_value: rawValue,
        value: compressValue(rawValue)  // 使用压缩后的值做布局
      }
    }),
    links: sankeyData.links.map(l => ({
      ...l,
      raw_value: +l.value || 0,
      value: compressValue(+l.value || 0)
    }))
  }

  sk(graph)

  const vExtent = d3.extent(graph.links, d => d.raw_value)
  const linkGray = d3.scaleLinear()
      .domain(vExtent[0] === vExtent[1] ? [0, vExtent[1]] : vExtent)
      .range(["#dddddd", "#444444"])

  // ===============================
  // compute entropy per node
  // ===============================
  graph.nodes.forEach(d => {
    d.entropy = honvisEntropyFromLinks(d.sourceLinks)
  })

  const entropies = graph.nodes.map(d => d.entropy)
  const maxEntropy = d3.max(entropies) || 1

  const entropyColor = d3.scaleLinear()
      .domain([0, maxEntropy])
      .range(["#2166ac", "#f7f7f7"])  // 深蓝 → 白

  /* links */
  const link = root.append("g")
      .selectAll("path")
      .data(graph.links)   // ⭐ 必须是 graph.links
      .enter()
      .append("path")
      .attr("d", sankeyLinkHorizontal())
      .attr("fill", "none")
      // .attr("stroke", '#bbb')
      .attr("stroke", d => getTokenColor(d.source.token, color))
      // .attr("stroke", d => linkGray(d.raw_value))
      .attr("stroke-opacity", 0.6)
      .attr("stroke-width", d => Math.max(1, d.width * 0.5 ))
      .on("mouseenter", function (event, d) {
        const tooltip = d3.select(tooltipRef.value)
        // 1️⃣ 淡化其它边，只高亮当前边
        link
            .transition()
            .duration(200)
            .attr("stroke-opacity", l => (l === d ? 0.9 : 0.05))

        // 3️⃣ tooltip
        tooltip
            .style("opacity", 1)
            .html(`
      <div><b>source</b>: ${getDisplayToken(d.source.token, legend)}</div>
      <div><b>target</b>: ${getDisplayToken(d.target.token, legend)}</div>
      <div><b>value</b>: ${d.raw_value ?? d.value}</div>
    `)
      })
      .on("mousemove", function (event) {
        moveTooltip(event)
      })
      .on("mouseleave", function () {
        // 1️⃣ 恢复所有边
        link
            .transition()
            .duration(200)
            .attr("stroke-opacity", 0.6)
            .attr("stroke", d => getTokenColor(d.source.token, color))
            // .attr("stroke", "#bbb")
        // .attr("stroke", d => linkGray(d.raw_value))

        // 2️⃣ 恢复光标
        d3.select(this).style("cursor", "default")

        // 3️⃣ 隐藏 tooltip
        d3.select(tooltipRef.value)
            .style("opacity", 0)
      })

  /* nodes */
  const node = root.append("g")
      .selectAll("g")
      .data(graph.nodes)
      .enter()
      .append("g")
      .attr("class", "node")

  node.append("rect")
      .attr("x", d => d.x0)
      .attr("y", d => d.y0)
      .attr("width", d => d.x1 - d.x0)
      .attr("height", d => d.y1 - d.y0)
      .attr("fill", d => getTokenColor(d.token, color))

  // node.append("text")
  //     .attr("x", d => d.x0 - 6)
  //     .attr("y", d => (d.y0 + d.y1) / 2)
  //     .attr("text-anchor", "end")
  //     .attr("dominant-baseline", "middle")
  //     .style("font-size", "11px")
  //     .text(d => `${d.class}`)

  node
      .on("mouseenter", function (event, d) {
        // 高亮与当前节点相关的边，其它边淡化
        link
            .transition()
            .duration(200)
            .attr("stroke-opacity", l =>
                (l.source === d || l.target === d) ? 0.9 : 0.05
            )

        const tooltip = d3.select(tooltipRef.value)
        // 添加鼠标手形光标
        d3.select(this).style("cursor", "pointer")

        tooltip
            .style("opacity", 1)
            .html(`
        <div><b>class</b>: ${getDisplayToken(d.token, legend)}</div>
        <div><b>in</b>: ${nodeInMap[d.id]}</div>
        <div><b>out</b>: ${nodeOutMap[d.id]}</div>
      `)
      })
      .on("mousemove", function (event) {
        moveTooltip(event)
      })
      .on("mouseleave", function () {
        // 恢复所有边
        link
            .transition()
            .duration(200)
            .attr("stroke-opacity", 0.6)

        d3.select(tooltipRef.value)
            .style("opacity", 0)
      })
}

/* ===============================
 * graph (FA2)
 * =============================== */
function renderFa2Graph(data) {
  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const seqs = data.first_order_sequences
  if (!seqs || seqs.length === 0) return

  const color = getColor()
  const width = svgRef.value.parentElement?.clientWidth || 800
  const height = svgRef.value.parentElement?.clientHeight || 600

  svg.attr("width", width).attr("height", height)

  const root = svg.append("g").attr("class", "root")
  const zoom = d3.zoom()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => {
        root.attr("transform", event.transform)
      })
  svg.call(zoom)
  svg.call(zoom.transform, d3.zoomIdentity)

  const nodeMap = new Map()
  const linkMap = new Map()

  seqs.forEach(seq => {
    seq.forEach(v => {
      const cls = String(v)
      const id = `node${cls}`
      if (!nodeMap.has(id)) nodeMap.set(id, { id, class: cls })
    })
    for (let i = 0; i < seq.length - 1; i++) {
      const s = `node${String(seq[i])}`
      const t = `node${String(seq[i + 1])}`
      const k = `${s}→${t}`
      if (!linkMap.has(k)) linkMap.set(k, { source: s, target: t, value: 0 })
      linkMap.get(k).value += 1
    }
  })

  const nodes = Array.from(nodeMap.values())
  const links = Array.from(linkMap.values())
  if (nodes.length === 0) return

  const values = links.map(d => d.value)
  const minV = d3.min(values) ?? 1
  const maxV = d3.max(values) ?? 1

  const linkGray = d3.scalePow()
      .exponent(0.8)
      .domain([minV, maxV])
      .range(["#eeeeee", "#444444"])
      .clamp(true)

  const linkOpacity = d3.scalePow()
      .exponent(0.8)
      .domain([minV, maxV])
      .range([0.2, 1])
      .clamp(true)

  const outMap = new Map()
  const inMap = new Map()
  links.forEach(l => {
    if (!outMap.has(l.source)) outMap.set(l.source, [])
    if (!inMap.has(l.target)) inMap.set(l.target, [])
    outMap.get(l.source).push(l)
    inMap.get(l.target).push(l)
  })

  nodes.forEach(n => {
    const outLs = outMap.get(n.id) || []
    const inLs = inMap.get(n.id) || []
    n.outFlow = d3.sum(outLs, d => d.value)
    n.inFlow = d3.sum(inLs, d => d.value)
    n.entropy = honvisEntropyFromLinks(outLs)
  })

  const layerMap = computeLayerMap(seqs)
  const maxLayer = d3.max(nodes, d => layerMap.get(String(d.class)) ?? 0) || 1

  const g = new Graph({ multi: true, type: "directed", allowSelfLoops: true })
  const xNorm = d3.scaleLinear().domain([0, maxLayer]).range([-500, 500])

  const NODE_R = 10

  nodes.forEach(n => {
    const L = layerMap.get(String(n.class)) ?? 0
    const initX = xNorm(L) * 0.5 + (Math.random() - 0.5) * 10
    const initY = (Math.random() - 0.5) * 10
    n.x = initX
    n.y = initY
    g.addNode(n.id, { ...n, x: initX, y: initY, size: NODE_R + 2 })
  })

  links.forEach((l, i) => {
    if (!g.hasNode(l.source) || !g.hasNode(l.target)) return
    g.addDirectedEdgeWithKey(
        `${l.source}→${l.target}#${i}`,
        l.source,
        l.target,
        { weight:  2000/(l.value ?? 1) }
    )
  })

  forceAtlas2.assign(g, {
    iterations: 10000,
    settings: {
      linLogMode: false,
      outboundAttractionDistribution: true,
      adjustSizes: true,
      gravity: 1,
      scalingRatio: 1,
      strongGravityMode: true,
      slowDown: 1,
      barnesHutOptimize: true,
      barnesHutTheta: 1.2,
      edgeWeightInfluence: 0
    }
  })

  nodes.forEach(n => {
    n.x = g.getNodeAttribute(n.id, "x")
    n.y = g.getNodeAttribute(n.id, "y")
  })

  const xs = nodes.map(d => d.x)
  const ys = nodes.map(d => d.y)
  const minX = d3.min(xs) ?? -1
  const maxX = d3.max(xs) ?? 1
  const minY = d3.min(ys) ?? -1
  const maxY = d3.max(ys) ?? 1
  const layoutW = (maxX - minX) || 1
  const layoutH = (maxY - minY) || 1
  const pad = 30

  nodes.forEach(n => {
    const scale = 0.5
    n.x = ((n.x - minX) / layoutW) * (width * scale) + width*(1-scale)/2
    n.y = ((n.y - minY) / layoutH) * (height * scale) + height*(1-scale)/2
  })

  const nodeById = new Map(nodes.map(n => [n.id, n]))
  links.forEach(l => {
    l.source = nodeById.get(l.source)
    l.target = nodeById.get(l.target)
  })

  const linkSel = root.append("g")
      .attr("class", "link-layer")
      .selectAll("path")
      .data(links)
      .enter()
      .append("path")
      .attr("fill", d => (d.source.id === d.target.id ? "none" : linkGray(d.value)))
      .attr("stroke", d => (d.source.id === d.target.id ? linkGray(d.value) : "none"))
      .attr("stroke-width", d => (d.source.id === d.target.id ? 2 : 0))
      .attr("stroke-linecap", "round")
      .attr("opacity", d => linkOpacity(d.value))
      .on("mouseenter", (event, d) => {
        showTooltip(
            `<b>source:</b> ${d.source.class}<br/><b>target:</b> ${d.target.class}<br/><b>value:</b> ${d.value}`,
            event
        )
        linkSel.attr("opacity", l => (l === d ? 1 : 0.08))
      })
      .on("mousemove", (event) => {
        moveTooltip(event)
      })
      .on("mouseleave", () => {
        hideTooltip()
        linkSel.attr("opacity", l => linkOpacity(l.value))
      })

  const nodeSel = root.append("g")
      .attr("class", "node-layer")
      .selectAll("g.node")
      .data(nodes)
      .enter()
      .append("g")
      .attr("class", "node")

  nodeSel.append("circle")
      .attr("r", NODE_R)
      .attr("fill", d => color(String(d.class)))
      .attr("stroke-width", 0.8)

  function refresh() {
    linkSel.attr("d", d => {
      if (d.source.id === d.target.id) return selfLoopTaperedPath(d, NODE_R * 2, NODE_R * 2, 0.4)
      return curvedTaperedLinkPath(d, 3, 1)
    })
    nodeSel.attr("transform", d => `translate(${d.x},${d.y})`)
  }

  nodeSel.call(
      d3.drag()
          .on("start", (event, d) => {
            d.fx = d.x
            d.fy = d.y
          })
          .on("drag", (event, d) => {
            d.fx = event.x
            d.fy = event.y
            d.x = event.x
            d.y = event.y
            refresh()
          })
          .on("end", (event, d) => {
            d.fx = null
            d.fy = null
            d.x = event.x
            d.y = event.y
            refresh()
          })
  )

  nodeSel
      .on("mouseenter", (event, d) => {
        d3.select(event.currentTarget).style("cursor", "pointer")
        showTooltip(
            `<b>class:</b> ${d.class}<br/><b>out-flow:</b> ${d.outFlow}<br/><b>in-flow:</b> ${d.inFlow}<br/>`,
            event
        )
        // nodeSel.attr("opacity", n => (n.id === d.id ? 1 : 0.25))
        linkSel.attr("opacity", l => (l.ensource.id === d.id || l.target.id === d.id) ? 1 : 0.01)
      })
      .on("mouseleave", () => {
        hideTooltip()
        nodeSel.attr("opacity", 1)
        linkSel.attr("opacity", l => linkOpacity(l.value))
      })
      .on("click", (event, d) => {
        event.stopPropagation()
        const rid = regionStore.activeRegionId
        const sourceRid = rid || "global"
        if (!brushStore.canEditActiveBrushFromRegion(sourceRid)) return

        if (rid) {
          brushStore.setActivePanelRegion(rid, "region")
        } else {
          brushStore.setActivePanelRegion("global", "global")
        }
        brushStore.toggleClass(String(d.class))
      })

  refresh()
}

/* ===============================
 * render
 * =============================== */
function renderSequenceGraph(data) {
  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  if (!data.raw_sequences || !data.sequence_ids) return

  const color = getColor()
  const { glyph, legend } = data
  const placeholder = legend.placeholder
  const tokens = legend.tokens.filter(t => t !== placeholder)

  // -------- build state2posIndex (same as force graph) --------
  const state2posIndex = new Map()
  Object.entries(data.state2pos || {}).forEach(([k, v]) => {
    state2posIndex.set(canonicalJsonKey(k), v)
  })

  // -------- build sid -> filteredIdx --------
  const filteredSeqId2Index = new Map()
  data.sequence_ids.forEach((sid, i) => {
    filteredSeqId2Index.set(String(sid), i)
  })

  // -------- slice sequences (same as force graph) --------
  let slicedSeqs

  if (!payloadStore.selectedStates || payloadStore.selectedStates.size === 0) {
    slicedSeqs = data.first_order_sequences
  }
  else {
    slicedSeqs = data.first_order_sequences
  }

  const seqs = slicedSeqs

  if (!seqs || seqs.length === 0) {
    svg.selectAll("*").remove()
    return
  }

  // -------- layout constants --------
  const MARGIN = 10
  const NODE_W = 20
  const NODE_H = 30
  const GAP_X = 2
  const GAP_Y = 10

  const nRows = seqs.length
  const nCols = d3.max(seqs, s => s.length) || 0

  // 计算内容实际需要的宽度
  const contentWidth = nCols * NODE_W + Math.max(0, (nCols - 1) * GAP_X)
  const contentHeight = nRows * NODE_H + Math.max(0, (nRows - 1) * GAP_Y)

  // 获取容器宽度
  const containerWidth = svgRef.value.parentElement.clientWidth

  // 动态计算边距：确保内容水平居中
  let leftMargin = MARGIN
  if (contentWidth + 2 * MARGIN < containerWidth) {
    leftMargin = Math.max(MARGIN, (containerWidth - contentWidth) / 2)
  }

  const canvasW = Math.max(containerWidth, contentWidth + 2 * leftMargin)
  const canvasH = contentHeight + 2 * MARGIN

  svg
      .attr("width", canvasW)
      .attr("height", canvasH)
      .style("min-width", `${contentWidth}px`) // 确保最小宽度

  // -------- zoom container --------
  const root = svg.append("g")
      .attr("class", "root")
      .attr("transform", "translate(0,0)")   // ⭐ 明确初始状态

  // -------- arrow marker (optional) --------
  const defs = svg.append("defs")
  defs.append("marker")
      .attr("id", "arrow-seq")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 10)
      .attr("refY", 0)
      .attr("markerWidth", 3)
      .attr("markerHeight", 3)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4 L9,0 L0,4 Z")
      .attr("fill", "#777")

  // -------- build node/link data --------
  const nodes = []
  const links = []
  const NODE_R = 8

  seqs.forEach((seq, r) => {
    for (let c = 0; c < seq.length; c++) {
      const id = `r${r}_c${c}`
      const token = seq[c]

      const x = MARGIN + c * (NODE_W + GAP_X) + NODE_W / 2
      const y = MARGIN + r * (NODE_H + GAP_Y) + NODE_H / 2

      nodes.push({ id, token, row: r, col: c, x, y })

      if (c < seq.length - 1) {
        links.push({
          source: id,
          target: `r${r}_c${c + 1}`,
          row: r
        })
      }
    }
  })

  const nodeById = new Map(nodes.map(n => [n.id, n]))

  // -------- draw links --------
  const linkSel = root.append("g")
      .attr("class", "link-layer")
      .selectAll("path")
      .data(links)
      .enter()
      .append("path")
      .attr("fill", "none")
      .attr("stroke", "#bbb")
      .attr("stroke-width", 1.5)
      // .attr("marker-end", "url(#arrow-seq)")
      .attr("d", (l) => {
        const s = nodeById.get(l.source)
        const t = nodeById.get(l.target)

        const x1 = s.x + NODE_R
        const y1 = s.y
        const x2 = t.x - NODE_R
        const y2 = t.y

        // 简单柔和曲线（同一行的水平连接）
        const mx = (x1 + x2) / 2
        return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`
      })

  // -------- draw nodes --------
  const nodeSel = root.append("g")
      .attr("class", "node-layer")
      .selectAll("g.node")
      .data(nodes)
      .enter()
      .append("g")
      .attr("class", "node")
      .attr("transform", d => `translate(${d.x},${d.y})`)

  nodeSel.append("circle")
      .attr("r", NODE_R)
      .attr("fill", d => getTokenColor(d.token, color))

  // nodeSel.append("text")
  //     .attr("x", -NODE_W / 2 - 2)
  //     .attr("y", -NODE_H / 2)
  //     .attr("text-anchor", "end")
  //     .attr("dominant-baseline", "middle")
  //     .style("font-size", "12px")
  //     .text(d => `${d.token}`)

  // -------- tooltip --------
  nodeSel
      .on("mouseenter", (event, d) => {
        showTooltip(
            `<b>class:</b> ${getDisplayToken(d.token, legend)}<br/>`,
            event
        )

        // 只高亮当前节点
        nodeSel.attr("opacity", n => (n.id === d.id ? 1 : 0.25))

        // 只高亮与该节点相连的边
        linkSel.attr("opacity", l =>
            (l.source === d.id || l.target === d.id) ? 1 : 0.15
        )
      })
      .on("mouseleave", () => {
        hideTooltip()
        linkSel.attr("opacity", 1)
        nodeSel.attr("opacity", 1)
      })
}

</script>

<template>
  <div class="seq-view-wrapper">
    <div class="seq-toolbar">
      <select
          v-model="viewMode"
          class="view-select"
          @pointerdown="onViewSelectPointerDown"
          @change="onViewSelectChange"
          @blur="onViewSelectBlur"
      >
        <option value="sequence">Sequence</option>
        <option value="sankey">Sankey</option>
        <option value="graph">Graph</option>
      </select>
    </div>

    <svg ref="svgRef"></svg>
    <div ref="tooltipRef" class="tooltip"></div>
  </div>
</template>

<style scoped>
.seq-view-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
  background: #fff;
  overflow: auto; /* 缩放/平移交给 zoom */
  text-align: left; /* 反转全局居中，避免列数少时 svg 被居中显示 */
}

/* 防止 svg 作为 inline 元素被 text-align 居中 */
.seq-view-wrapper svg {
  display: block;
  margin: 0;
}

.tooltip {
  position: absolute;
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
  z-index: 1000;
}
.seq-toolbar {
  position: sticky;
  top: 0;
  padding: 6px 8px;
  z-index: 10;
  background: linear-gradient(180deg, #fbfcfe, #f2f5f8);
  border-bottom: 1px solid var(--panel-border);
}

.seq-toolbar .view-select {
  padding: 4px 28px 4px 9px;
  border-radius: 5px;
  background: #fff;
  color: var(--text-main);
  cursor: pointer;
  border: 1px solid var(--panel-border);
  font-size: 12px;
}

.seq-toolbar .view-select:hover {
  background: var(--accent-soft);
  border-color: rgba(47, 111, 159, 0.45);
}

.seq-toolbar .view-select:focus,
.seq-toolbar .view-select:active {
  outline: 2px solid rgba(47, 111, 159, 0.18);
  background: #fff;
}

</style>

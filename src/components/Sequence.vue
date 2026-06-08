<script setup>
import { ref, watch, computed
} from "vue"
import * as d3 from "d3"
import { usePayloadStore } from "@/store/payloadStore.js"
import {
  sliceSequencesByStatePos,
  canonicalJsonKey, honvisEntropyFromLinks
} from "./tool.js"
import { drawGlyphForce } from "./drawGlyphForce.js"
import {sankey, sankeyLinkHorizontal} from "d3-sankey";
import { useRegionStore } from "@/store/regionStore.js"

/* ===============================
 * refs & store
 * =============================== */
const payloadStore = usePayloadStore()
const regionStore = useRegionStore()
const svgRef = ref(null)
const tooltipRef = ref(null)
// 切换是序列图还是桑基图
const viewMode = ref("sequence")   // "sequence" | "sankey"

const sequenceData = computed(() => {

  const rid = regionStore.activeRegionId
  // ⭐ 如果没有任何 region 被选中：显示全量
  if (!rid) {
    return payloadStore.payload
  }

  const region = regionStore.regions[rid]

  if (!region) return payloadStore.payload

  // ⭐ 如果 region 没有数据 → fallback 全量
  if (!region.sequences || region.sequences.length === 0 ) {
    return payloadStore.payload
  }

  return {
    ...payloadStore.payload,
    raw_sequences: region.sequences || [],
    sequence_ids: region.sequenceIds || []
  }

})

/* ===============================
 * watch: keep consistent with force graph
 * =============================== */
watch(
    () => [
      sequenceData.value,
      payloadStore.payload,
      viewMode.value
    ],
    ([data, selected]) => {

      if (!data) {
        d3.select(svgRef.value).selectAll("*").remove()
        return
      }

      if (!selected || selected.size === 0) {
        renderByMode(data)
        return
      }

      renderByMode(data)
    }
)


// 桑基图和序列图的切换函数
function toggleView() {
  viewMode.value =
      viewMode.value === "sequence" ? "sankey" : "sequence"
}

function renderByMode(data) {
  if (!data) {
    d3.select(svgRef.value).selectAll("*").remove()
    return
  }

  if (viewMode.value === "sequence") {
    renderSequenceGraph(data)
  } else if (viewMode.value === "sankey") {
    renderSankeyGraph(data)
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
          class: cls,
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

  const seqs = data.raw_sequences

  if (!seqs || seqs.length === 0) {
    renderSankey(payloadStore.payload)
    return
  }

  if (!seqs || seqs.length === 0) return


  const sankeyData = buildSankeyFromSequences(seqs)

  renderSankey({
    sankey: sankeyData,
    glyph: data.glyph,
    legend: data.legend
  })

}

function drawGlyph(nodeSel, glyphData, tokens, color) {
  nodeSel.each(function (d) {
    d3.select(this).selectAll(".glyph").remove()  //

    const ginfo = glyphData[String(d.class)]

    if (!ginfo) return

    const posDist = ginfo.position_distributions
    const maxOrder = ginfo.max_order

    const padding = 6
    const gap = 6

    // 1️⃣ 节点内部可用空间（必须最先算）
    const availableW = d.x1 - d.x0 - 2 * padding
    const availableH = Math.max(20, d.y1 - d.y0 - 2 * padding)

    // 2️⃣ 根据横向 step 数量，确定 pie 半径
    const perStepW = availableW / maxOrder

    const r = Math.max(
        5,
        Math.min(
            14,
            (perStepW - gap) / 2,   // 横向不溢出
            availableH / 2 - 2      // 纵向不溢出
        )
    )

    const arc = d3.arc().innerRadius(0).outerRadius(r)
    const pie = d3.pie().sort(null).value(d => d.value)

    // ===============================
    // NEW: 按"有效位置"重排 glyph
    // ===============================

    // 1️⃣ 先过滤出"有效位置"
    const valid = posDist
        .map((dist, i) => {
          const entries = tokens
              .map(t => ({ token: t, value: dist[t] || 0 }))
              .filter(d => d.value > 0)
          return { i, entries }
        })
        .filter(x => x.entries.length > 0)

    // 没有有效 pie，直接不画
    const effectiveSteps = valid.length
    if (effectiveSteps === 0) return

    // 2️⃣ 用有效 pie 数量来决定宽度并居中
    const totalGlyphW = effectiveSteps * (2 * r + gap) - gap
    const gx = d.x0 + padding + (availableW - totalGlyphW) / 2
    const gy = d.y0 + padding

    const g = d3.select(this)
        .append("g")
        .attr("class", "glyph")
        .attr("transform", `translate(${gx}, ${gy})`)

    // 3️⃣ 按 j=0..effectiveSteps-1 画，保证居中
    valid.forEach((item, j) => {
      const cx = j * (2 * r + gap) + r
      const cy = availableH / 2

      const pg = g.append("g")
          .attr("transform", `translate(${cx}, ${cy})`)

      pg.selectAll("path")
          .data(pie(item.entries))
          .enter()
          .append("path")
          .attr("d", arc)
          .attr("fill", d => color(d.data.token))
          .attr("stroke", "#fff")
          .attr("stroke-width", 0.8)

      // （可选）显示原始位置编号
      // g.append("text")
      //   .attr("x", cx)
      //   .attr("y", availableH + 8)
      //   .attr("text-anchor", "middle")
      //   .style("font-size", "9px")
      //   .text(`p${item.i + 1}`)
    })

  })
}

function renderSankey(data) {
  const { sankey: sankeyData, glyph, legend } = data

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

  // ==========================
  // pos 归一化：避免子图列数少但 pos 从很大值开始，导致左侧出现大量空列
  // ==========================
  const rawPosValues = (sankeyData.nodes || [])
      .map(n => +n.pos)
      .filter(v => Number.isFinite(v))
  const posMin = rawPosValues.length ? d3.min(rawPosValues) : 0

  // ==========================
  // (NEW) value 压缩：缩小极端差距
  // ==========================
  // 节点“爆大”的根因通常是 value 差距太大（d3-sankey 用 value 直接决定节点高度）。
  // 这里同时做：
  // 1) 对极端 outlier 做上截断（分位数 cap）
  // 2) 用对数/幂次压缩（log/sqrt/pow）
  const COMPRESS_MODE = "log"   // "sqrt" | "pow" | "log"
  const ALPHA = 0.5             // pow 模式才用：0.3~0.6
  const CAP_QUANTILE = 0.95     // 0.9~0.98：越小压得越狠（outlier 越不影响布局）

  // 取 links 的原始 value（更可靠，因为 node.value 通常由 link 决定）
  const rawLinkValues = sankeyData.links.map(l => +l.value || 0)
  const maxV = d3.max(rawLinkValues) || 1
  const sortedLinkValues = rawLinkValues.slice().sort((a, b) => a - b)
  const capV = d3.quantile(sortedLinkValues, CAP_QUANTILE) ?? maxV

  // 压缩函数：输入 raw value，输出显示用 value（给 sankey 用）
  const compressValue = (v) => {
    v = Math.max(0, +v || 0)
    // outlier cap：避免少数超大边把某些节点撑到很高
    v = Math.min(v, capV)
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


  const placeholder = legend.placeholder
  const tokens = legend.tokens.filter(t => t !== placeholder)

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
  const glyphWidth =
      maxOrder * (2 * GLYPH_R + GLYPH_GAP) - GLYPH_GAP

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
        pos: (Number.isFinite(+n.pos) ? (+n.pos - posMin) : n.pos),
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

  // 不同列节点之间的间距
  const columnGap = 140
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
        pos: (Number.isFinite(+n.pos) ? (+n.pos - posMin) : n.pos),
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
      .attr("stroke", '#bbb')
      // .attr("stroke", d => linkGray(d.raw_value))
      .attr("stroke-opacity", 0.9)
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
      <div><b>source</b>: ${d.source.class}</div>
      <div><b>target</b>: ${d.target.class}</div>
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
            .attr("stroke-opacity", 0.9)
            .attr("stroke", "#bbb")
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
      .attr("fill", "#f5f5f5")
      .attr("stroke", "#d0d0d0")
      // .attr("stroke", d => entropyColor(d.entropy))
      .attr("stroke-width", 1.5)
      .attr("rx", 5)

  node.append("text")
      .attr("x", d => d.x0 - 6)
      .attr("y", d => (d.y0 + d.y1) / 2)
      .attr("text-anchor", "end")
      .attr("dominant-baseline", "middle")
      .style("font-size", "11px")
      .text(d => `${d.class}`)

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
        <div><b>class</b>: ${d.class}</div>
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

  const color = payloadStore.colorScale
  drawGlyph(node, glyph, tokens, color)
}

/* ===============================
 * render
 * =============================== */
function renderSequenceGraph(data) {
  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  if (!data.raw_sequences || !data.sequence_ids) return

  const { glyph, legend } = data
  const placeholder = legend.placeholder
  const tokens = legend.tokens.filter(t => t !== placeholder)
  const color = buildColorScale(tokens)

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

  // if (!payloadStore.selectedStates || payloadStore.selectedStates.size === 0) {
  //   // ⭐ 无选中：直接画完整序列
  //   slicedSeqs = data.raw_sequences
  // }
  // else {slicedSeqs = sliceSequencesByStatePos(
  //     data.raw_sequences,
  //     filteredSeqId2Index,
  //     state2posIndex,
  //     payloadStore.selectedStates,
  //     payloadStore.prevSteps,
  //     payloadStore.nextSteps,
  //     payloadStore.windowMode
  // )}


  // if (!slicedSeqs || slicedSeqs.length === 0) {
  //   svg.selectAll("*").remove()
  //   return
  // }
  //

  if (!payloadStore.selectedStates || payloadStore.selectedStates.size === 0) {
    // ⭐ 无选中：直接画完整序列
    slicedSeqs = data.raw_sequences
  }
  else {
    slicedSeqs = payloadStore._classSeqs || []
  }

  const seqs = slicedSeqs

  if (!seqs || seqs.length === 0) {
    svg.selectAll("*").remove()
    return
  }

  // -------- layout constants --------
  const MARGIN = 30
  const NODE_W = 60
  const NODE_H = 30
  const GAP_X = 26
  const GAP_Y = 18

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

  seqs.forEach((seq, r) => {
    for (let c = 0; c < seq.length; c++) {
      const id = `r${r}_c${c}`
      const cls = seq[c]

      const x = MARGIN + c * (NODE_W + GAP_X) + NODE_W / 2
      const y = MARGIN + r * (NODE_H + GAP_Y) + NODE_H / 2

      nodes.push({ id, class: cls, row: r, col: c, x, y })

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

        const x1 = s.x + NODE_W / 2
        const y1 = s.y
        const x2 = t.x - NODE_W / 2
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

  // 背板 + 外框（这里不算 entropy，就先用统一灰色；你也可以算“局部出边熵”来映射）
  nodeSel.append("rect")
      .attr("x", -NODE_W / 2)
      .attr("y", -NODE_H / 2)
      .attr("width", NODE_W)
      .attr("height", NODE_H)
      .attr("rx", 5)
      .attr("fill", "#f5f5f5")
      .attr("stroke", "#d0d0d0")
      .attr("stroke-width", 1.5)

  // 左侧 class 文本（跟你力导向图一致）
  nodeSel.append("text")
      .attr("x", -NODE_W / 2 - 6)
      .attr("y", -NODE_H / 2)
      .attr("text-anchor", "end")
      .attr("dominant-baseline", "middle")
      .style("font-size", "12px")
      .text(d => `${d.class}`)

  // glyph（复用你的函数：同力导向图）
  drawGlyphForce(nodeSel, glyph, tokens, color, NODE_W* 0.8, NODE_H* 0.8)

  // -------- tooltip --------
  nodeSel
      .on("mouseenter", (event, d) => {
        showTooltip(
            `<b>class:</b> ${d.class}<br/>`,
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

/* ===============================
 * utils
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
</script>

<template>
  <div class="seq-view-wrapper">
    <div class="seq-toolbar">
      <button @click="toggleView">
        {{ viewMode === 'sequence' ? 'Switch to Sankey' : 'Switch to Sequence' }}
      </button>
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
  z-index: 1000;
}
.seq-toolbar {
  position: sticky;
  top: 0;
  padding: 6px 6px;
  z-index: 10;
}

.seq-toolbar button {
  padding: 4px 10px;
  border-radius: 4px;
  background: #f6f6f6;
  color: #606266;
  cursor: pointer;
}

.seq-toolbar button:hover {
  background: #eaeaea;
}

.seq-toolbar button:focus,
.seq-toolbar button:active {
  outline: none;
  background: #f6f6f6;
}

</style>

<script setup>
import { onMounted, ref } from "vue"
import * as d3 from "d3"
import { sankey, sankeyLinkHorizontal } from "d3-sankey";
import { honvisEntropyFromLinks } from "./tool.js";
import { apiUrl } from "@/api"

/* ===============================
 * refs
 * =============================== */
const svgRef = ref(null)
const legendRef = ref(null)
const file = ref(null)
const payload = ref(null)
const tooltipRef = ref(null)

// ------------------------
// 文件选择
// ------------------------
function onFileChange(e) {
  file.value = e.target.files[0]
  upload()
}

// ------------------------
// 上传文件
// ------------------------
async function upload() {
  if (!file.value) return

  const form = new FormData()
  form.append("file", file.value)

  const res = await fetch(apiUrl("/api/upload"), {
    method: "POST",
    body: form
  })

  if (!res.ok) {
    const err = await res.json()
    alert(err.error || "Upload failed")
    return
  }

  const data = await res.json()   // ✅ 直接用上传返回
  payload.value = data
  render(data)
}

// ------------------------
// 渲染
// ------------------------
function render(data) {
  renderSankey(data)
}

/* ===============================
 * color scale
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

/* ===============================
 * legend
 * =============================== */
function renderLegend(el, tokens, color) {
  const root = d3.select(el)
  root.selectAll("*").remove()

  root.append("div")
      .style("font-weight", "600")
      .style("margin-bottom", "8px")
      .text("first_order_node")

  const item = root.selectAll(".legend-item")
      .data(tokens)
      .enter()
      .append("div")
      .attr("class", "legend-item")

  item.append("div")
      .attr("class", "swatch")
      .style("width", "14px")
      .style("height", "14px")
      .style("border", "1px solid #999")
      .style("background-color", d => color(d))


  item.append("div").text(d => d)
}

/* ===============================
 * glyph (multi-position pies)
 * =============================== */
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

/* ===============================
 * main render
 * =============================== */
function renderSankey(data) {

  const svg = d3.select(svgRef.value)

  const legendEl = legendRef.value
  svg.selectAll("*").remove()

  const { sankey: sankeyData, glyph, legend } = data

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


  const placeholder = legend.placeholder
  const tokens = legend.tokens.filter(t => t !== placeholder)

  const color = buildColorScale(tokens)
  renderLegend(legendEl, tokens, color)


  const height = +svg.attr("height")

  // —— glyph 固定参数（全局常数）——
  const GLYPH_R = 10
  const GLYPH_GAP = 6
  const GLYPH_PADDING = 6
  const MIN_NODE_HEIGHT =
      4 * GLYPH_R +
      4 * GLYPH_PADDING +
      20;   // ⭐ 给文本 / stroke / 误差余量

  const NODE_PADDING = 16   // 10~14 是非常常见的稳定区间


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

  // const probeGraph = {
  //   nodes: sankeyData.nodes.map(d => ({ ...d })),
  //   links: sankeyData.links.map(d => ({ ...d }))
  // }

  const probeGraph = {
    nodes: sankeyData.nodes.map(n => {
      // 同样计算原始流量
      const incoming = sankeyData.links.filter(l => l.target === n.id)
      const outgoing = sankeyData.links.filter(l => l.source === n.id)
      const inSum = d3.sum(incoming, l => +l.value || 0)
      const outSum = d3.sum(outgoing, l => +l.value || 0)
      const rawValue = Math.max(inSum, outSum)

      return {
        ...n,
        raw_value: rawValue,
        value: compressValue(rawValue)
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
      (maxNodesInColumn - 1) * NODE_PADDING +
      20

  const finalHeight = Math.max(
      minRequiredHeight * 1.3,
      +svg.attr("height")   // 不比原来小
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
      .nodeAlign(d => d.pos)   // ⭐ 核心：用后端给的 pos 作为列
      .extent([
        [leftMargin, 10],
        [requiredWidth - rightMargin, finalHeight - 10]
      ])


  const graph = {
    nodes: sankeyData.nodes.map(n => {
      // 计算每个节点的原始流量
      const incoming = sankeyData.links.filter(l => l.target === n.id)
      const outgoing = sankeyData.links.filter(l => l.source === n.id)
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
  const link = svg.append("g")
      .selectAll("path")
      .data(graph.links)   // ⭐ 必须是 graph.links
      .enter()
      .append("path")
      .attr("d", sankeyLinkHorizontal())
      .attr("fill", "none")
      .attr("stroke", "#bbb")
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
      <div><b>source</b>: ${d.source.class}</div>
      <div><b>target</b>: ${d.target.class}</div>
      <div><b>value</b>: ${d.raw_value ?? d.value}</div>
    `)
      })
      .on("mousemove", function (event) {
        d3.select(tooltipRef.value)
            .style("left", event.pageX + 12 + "px")
            .style("top", event.pageY - 12 + "px")
      })
      .on("mouseleave", function () {

        // 1️⃣ 恢复所有边
        link
            .transition()
            .duration(200)
            .attr("stroke-opacity", 0.6)
            .attr("stroke", "#bbb")

        // 2️⃣ 恢复光标
        d3.select(this).style("cursor", "default")

        // 3️⃣ 隐藏 tooltip
        d3.select(tooltipRef.value)
            .style("opacity", 0)
      })



  /* nodes */
  const node = svg.append("g")
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
      .attr("stroke", d => entropyColor(d.entropy))

      .attr("stroke-width", 2)

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
        <div><b>num</b>: ${d.raw_value}</div>
      `)
      })
      .on("mousemove", function (event) {
        d3.select(tooltipRef.value)
            .style("left", event.pageX + 12 + "px")
            .style("top", event.pageY - 12 + "px")
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


  drawGlyph(node, glyph, tokens, color)
}

</script>

<template>
  <div class="sankey-container">
    <div class="sankey-header">
      <div class="control">
        <input type="file" @change="onFileChange" />
      </div>
    </div>

    <div class="sankey-content">
      <!-- 只有一个.svg-section，内部包含图例和SVG -->
      <div class="svg-section">
        <!-- 图例放在这里，可以用绝对定位 -->
        <div ref="legendRef" class="legend"></div>

        <!-- 提示框 -->
        <div ref="tooltipRef" class="tooltip"></div>

        <!-- SVG -->
        <svg ref="svgRef"></svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sankey-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  box-sizing: border-box;
}

.sankey-header {
  flex-shrink: 0;
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
  overflow: auto; /* 添加滚动条查看完整SVG */
}

.legend {
  font-size: 12px;
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 10px 14px;
}

.legend-item {
  display: inline-flex;
  flex-direction: row;
  align-items: center;
  gap: 6px;
  margin: 0;
}

.legend-item > div:last-child {
  order: 1;
}

.legend-item > .swatch {
  order: 2;
}

.swatch {
  width: 14px;
  height: 14px;
  border: 1px solid #999;
  box-sizing: border-box;
  display: inline-block;
  vertical-align: middle;
}

.node rect {
  cursor: default;
}

.link {
  pointer-events: none;
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

.svg-section svg {
  display: block;
  border: 1px solid #c0c0c0; /* 银灰色边框 */
  border-radius: 4px;
  background-color: #ffffff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

/* 文件输入样式 */
.control input[type="file"] {
  padding: 6px 12px;
  border: 1px solid #c0c0c0;
  border-radius: 4px;
  background-color: #f8f8f8;
  font-size: 14px;
  cursor: pointer;
}

.control input[type="file"]:hover {
  border-color: #a0a0a0;
  background-color: #f0f0f0;
}
</style>

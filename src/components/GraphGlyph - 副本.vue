<script setup>
import {ref, watch, computed } from "vue"
import { Upload } from "@element-plus/icons-vue"
import * as d3 from "d3"
import { computeLayerMap, selfLoopTaperedPath, curvedTaperedLinkPath, entropyFromLinks } from "./tool.js";
import { usePayloadStore } from "@/store/payloadStore.js"
import { useBrushStore } from "@/store/brushStore.js"
import { drawGlyphForce } from "./drawGlyphForce.js"
import { useRegionStore } from "@/store/regionStore.js"

/* ===============================
 * refs
 * =============================== */
const svgRef = ref(null)
const nodeSelRef = ref(null)
const linkSelRef = ref(null) // 可选
const legendRef = ref(null)
const file = ref(null)
const payload = ref(null)
const tooltipRef = ref(null)
const payloadStore = usePayloadStore()
const fileInput = ref(null)
const linkGrayRef = ref(null)

const brushStore = useBrushStore()
const regionStore = useRegionStore()
const updateHighlightStylesFn = ref(null)  // ⭐ 新增

const currentSourceRegion = computed(() => {
  const rid = regionStore.activeRegionId

  console.log("rid",rid)

  if (!rid || rid === "global") {
    return { id: "global", type: "global" }
  }
  return { id: rid, type: "region" }
})

watch(
    () => regionStore.regions["global"]?.highlightNodes,
    () => {

      updateHighlightStylesFn.value?.()
    },
    { deep: true }
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
async function upload() {
  if (!file.value) return

  const form = new FormData()
  form.append("file", file.value)

  const res = await fetch("http://localhost:8000/api/upload", {
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

  // ✅ 新增：写入全局 store
  payloadStore.setPayload(data)
  render(data)
}


// ------------------------
// 渲染
// ------------------------
function render(data) {
  renderGraph(data)
}

/* ===============================
 * legend
 * =============================== */
function renderLegend(el, tokens, color) {
  const root = d3.select(el)
  root.selectAll("*").remove()

  // 确保容器本身是 flex
  root.style("display", "flex")
      .style("align-items", "center")
      .style("flex-wrap", "nowrap")

  // root.append("span")
  //     .style("font-weight", "600")
  //     .style("margin-bottom", "8px")
  //     .text("first_order_node")
  //     .style("margin-right", "12px") // 距离右侧图标的间距
  //     .style("white-space", "nowrap")

  const item = root.selectAll(".legend-item")
      .data(tokens)
      .enter()
      .append("div")
      .attr("class", "legend-item")

  item.append("div")
      .attr("class", "swatch")
      .style("width", "15px")
      .style("height", "15px")
      // .style("border", "1px solid #999")
      .style("background-color", d => color(d))


  item.append("div").text(d => d)
}

function showTooltip(html, event) {
  const el = d3.select(tooltipRef.value)

  el.html(html)
      .style("left", event.offsetX + 12 + "px")
      .style("top", event.offsetY + 12 + "px")
      .style("opacity", 1)
}

function hideTooltip() {
  d3.select(tooltipRef.value)
      .style("opacity", 0)
}

// 多 brush 命中 → 先命中的那个颜色（后面可升级）
function updateNodeHighlight() {
  const nodeSel = nodeSelRef.value
  if (!nodeSel) return

  const brushes = Object.values(brushStore.brushes)
  const active = brushStore.activeBrush

  nodeSel.select("rect")
      .attr("stroke", d => {
        const hit = brushes.find(b =>
            b.classes.has(String(d.class))
        )
        return hit ? hit.color : "#aaa"
      })
      .attr("stroke-width", d => {
        if (!active) return 1.5
        return active.classes.has(String(d.class)) ? 3 : 1.5
      })
}


function updateLinkHighlight() {
  const linkSel = linkSelRef.value
  if (!linkSel) return

  const b = brushStore.activeBrush
  if (!b || b.classes.size === 0) {
    linkSel.attr("opacity", 1)
    return
  }

  const sel = b.classes

  linkSel.attr("opacity", l => {
    const sIn = sel.has(String(l.source.class))
    const tIn = sel.has(String(l.target.class))
    return (sIn || tIn) ? 1 : 0.05
  })
}

/* ===============================
 * main render
 * =============================== */
function renderGraph(data) {

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
  renderLegend(legendRef.value, tokens, color)

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

  // ⭐ 设置初始缩放为 1/4
  svg.call(
      zoom.transform,
      d3.zoomIdentity
          .translate(width / 4, height / 4)
          .scale(0.5)
  )

  // 复制数据（d3-force 会改对象）
  const nodes = graph.nodes.map(d => ({ ...d }))
  const links = graph.links.map(d => ({ ...d }))

  // ⭐ 预计算 edge key
  links.forEach(l => {
    const sid = typeof l.source === "object" ? l.source.id : l.source
    const tid = typeof l.target === "object" ? l.target.id : l.target
    l._key = `${sid}→${tid}`
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

  const entropyColor = d3.scaleLinear()
      .domain([0, maxEntropy])
      .range(["#2166ac", "#f7f7f7"])

  // ===== 流量深浅的映射 =====
  const linkGray = d3.scaleLinear()
      .domain(d3.extent(links, d => d.value))
      .range(["#dddddd", "#444444"])   // 浅灰 → 深灰

  linkGrayRef.value = linkGray   // ✅ 新增

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

  // 建索引：edgeKey -> DOM 元素（高亮更新用，避免每次扫全量 linkSel）
  const linkElByKey = new Map()
  linkSel.each(function(d) {
    linkElByKey.set(edgeKey(d), this)
  })

  linkSel
      .on("mouseenter", function(event, d) {
        d3.select(this).style("cursor", "pointer")

        showTooltip(
            `${d.source.class} → ${d.target.class}<br/>value: ${d.value}`, event)
      })
      .on("mouseleave", function() {
        hideTooltip()
      })
      .on("click", (event, d) => {

        event.stopPropagation()
        // 说明我现在在对全量图进行brush
        brushStore.setActivePanelRegion(
            "global",
            "global"
        )

        // brushStore.setActivePanelRegion(
        //     currentSourceRegion.value.id,
        //     currentSourceRegion.value.type
        // )
        if (!brushStore.activeBrushId) return

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

  nodeSel
      .on("mouseenter", function(event, d) {
        d3.select(this).style("cursor", "pointer")

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
      .on("click", (event, d) => {

        event.stopPropagation()

        brushStore.setActivePanelRegion(
            "global",
            "global"
        )

        // brushStore.setActivePanelRegion(
        //     currentSourceRegion.value.id,
        //     currentSourceRegion.value.type
        // )
        brushStore.toggleClass(String(d.class))
      })


  const NODE_W = 150
  const NODE_H = 70

  nodeSel.append("rect")
      .attr("x", -NODE_W/2)
      .attr("y", -NODE_H/2)
      .attr("width", NODE_W)
      .attr("height", NODE_H)
      .attr("rx", 10)
      .attr("fill", "#f5f5f5")
      // .attr("stroke", d => entropyColor(d.entropy))
      .attr("stroke", "#aaa")
      .attr("stroke-width", 2)

  // 建索引：nodeId -> rect DOM 元素（高亮更新用）
  const nodeRectElById = new Map()
  nodeSel.each(function(d) {
    const rect = d3.select(this).select("rect").node()
    if (rect) nodeRectElById.set(d.id, rect)
  })

  // 节点旁边的文字
  nodeSel.append("text")
      .attr("x", -NODE_W/2 - 6)
      .attr("y", 0)
      .attr("text-anchor", "end")
      .attr("dominant-baseline", "middle")
      .style("font-size", "20px")
      .text(d => `${d.class}`)

  // glyph
  drawGlyphForce(nodeSel, glyph, tokens, color, NODE_W, NODE_H)

  const layerMap = computeLayerMap(data.raw_sequences)
  const maxLayer = d3.max(nodes, d => layerMap.get(String(d.class)) ?? 0) || 1
  const xScale = d3.scaleLinear().domain([0, maxLayer]).range([20, width - 20])

  // 初始化节点位置（很关键）
  nodes.forEach(n => {
    const L = layerMap.get(String(n.class)) ?? 0
    n.x = xScale(L) + (Math.random() - 0.5) * 20
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
    const ds = outMap.get(d.source.id)?.length || 0
    const dt = outMap.get(d.target.id)?.length || 0
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

  function updateHighlightStyles() {
    sim.stop()

    const r = regionStore.regions["global"]

    const highlightNodes = r?.highlightNodes ?? new Set()
    const highlightEdges = r?.highlightEdges ?? new Set()

    const hasHighlight =
        highlightNodes.size > 0 ||
        highlightEdges.size > 0

    const active = brushStore.activeBrush

    nodeSel.select("rect")
        .attr("stroke", d => {
          if (!active) return "#aaa"
          if (!highlightNodes) return "#aaa"
          const hit = highlightNodes.has(d.id)
          return hit ? active.color : "#aaa"
        })
        .attr("stroke-width", d => {
          if (!active) return 1.5
          return highlightNodes.has(d.id) ? 3 : 1.5
        })

    // 边
    linkSel
        .attr("opacity", d => {
          if (!hasHighlight) return 0.9
          return highlightEdges.has(edgeKey(d)) ? 1 : 0.05
        })
        .attr("fill", d => {
          const sid = d.source
          const tid = d.target
          if (!hasHighlight) return sid !== tid ? linkGray(d.value) : "none"
          const k = edgeKey(d)
          if (highlightEdges.has(k)) return sid !== tid ? (active?.color ?? "#ff5500") : "none"
          return sid !== tid ? linkGray(d.value) : "none"
        })
        .attr("stroke", d => {
          const sid = d.source
          const tid = d.target
          if (!hasHighlight) return sid === tid ? linkGray(d.value) : "none"
          const k = edgeKey(d)
          if (highlightEdges.has(k)) return sid === tid ? (active?.color ?? "#ff5500") : "none"
          return sid === tid ? linkGray(d.value) : "none"
        })
  }
  // ⭐ 注册到组件级 ref
  updateHighlightStylesFn.value = updateHighlightStyles

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

  // 修改 x 轴力的强度，增加水平约束
  sim.force("x", d3.forceX(d => {
    const L = layerMap.get(String(d.class)) ?? 0
    return xScale(L)
  }).strength(0.1))
      .force("y", d3.forceY(height/2).strength(0.2))

  // sim.on("tick", () => {
  //   linkSel.attr("d", d => curvedTaperedLinkPath(d, 10, 1))
  //   nodeSel.attr("transform", d => `translate(${d.x},${d.y})`)
  // })

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

</script>

<template>
  <div class="graph-container">
    <div class="legend-row"
         @click="regionStore.setActive('global')">
      <div class="control">
        <input ref="fileInput" type="file" class="hidden-file-input" @change="onFileChange" />
        <div class="upload-btn" @click="triggerUpload">
          <el-icon :size="22"><Upload /></el-icon>
          <span class="label">Upload</span>
        </div>
      </div>
      <div ref="legendRef" class="legend"></div>

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
  gap: 12px;
  padding: 0px;
  background: white;
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

.legend {
  font-size: 12px;
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  padding: 10px;
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
  width: 99.8%;
  height: 99.8%;
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

.legend-row {
  display: flex;
  align-items: center; /* 垂直居中 */
  gap: 20px;           /* 按钮和 legend 之间的间距 */
  width: 100%;
  flex-wrap: nowrap;   /* 强制不换行 */
  background: #f5f5f5;
}

/* 文件上传样式 */
.hidden-file-input {
  display: none;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  padding: 0px 10px;
  margin-left: 10px;
  border-radius: 6px;
  cursor: pointer;
  background: #f6f6f6;
  color: #606266;
  border: 1px solid #dcdfe6;
  transition: all 0.2s ease;
}


.upload-btn:hover{
  background: #eaeaea;
}

.upload-btn:active {
  transform: scale(0.97);
}

.label {
  font-size: 13px;
}
</style>
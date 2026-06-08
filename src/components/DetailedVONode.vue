<script setup>
import { ref, watch } from "vue"
import * as d3 from "d3"
import { usePayloadStore } from "@/store/payloadStore"

/* ============================
 * refs & store
 * ============================ */
const svgRef = ref(null)
const store = usePayloadStore()

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

/* ============================
 * color scale (reuse GraphGlyph)
 * ============================ */
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

/* ============================
 * main render
 * ============================ */
function render(data) {
  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const raw2first = data.raw2first || {}
  const tokens = data.legend?.tokens || []

  const color = buildColorScale(tokens)

  /* ---- layout ---- */
  const panelW = 145
  const panelH = 220
  const panelsPerRow = 2
  const gapX = 10
  const gapY = 16

  let cursorX = 0
  let cursorY = 0
  let usedMaxWidth = 0

  const root = svg.append("g")
      .attr("transform", "translate(8,20)")

  Object.keys(raw2first).forEach((firstNode) => {

    const maxRowWidth =
        panelsPerRow * panelW + (panelsPerRow - 1) * gapX

    if (cursorX + panelW > maxRowWidth) {
      cursorX = 0
      cursorY += panelH + gapY
    }

    const panel = root.append("g")
        .attr("transform", `translate(${cursorX},${cursorY})`)

    cursorX += panelW + gapX
    usedMaxWidth = Math.max(usedMaxWidth, cursorX)

    /* ---- border ---- */
    panel.append("rect")
        .attr("width", panelW)
        .attr("height", panelH)
        .attr("rx", 10)
        .attr("fill", "#fafafa")
        .attr("stroke", "#ccc")

    /* ---- title ---- */

    const titleG = panel.append("g")
        .attr("transform", "translate(10,16)")

    titleG.append("circle")
        .attr("cx", 0)
        .attr("cy", -4)
        .attr("r", 5)
        .attr("fill", color(String(firstNode)))

    titleG.append("text")
        .attr("x", 10)
        .attr("y", 0)
        .style("font-size", "12px")
        .style("font-weight", "600")
        .text(`${firstNode}`)


    drawRawFirstPanel(
        panel,
        raw2first[firstNode],
        firstNode,
        color,
        panelW,
        panelH
    )
  })

  /* ---- final svg size ---- */
  svg.attr("width", usedMaxWidth + 40)
  svg.attr("height", cursorY + panelH + 40)
}

/* ============================
 * draw raw_event list
 * ============================ */
function drawRawFirstPanel(
    panel,
    rawEvents,
    firstNode,
    color,
    panelW,
    panelH
) {
  const viewW = panelW - 20
  const viewH = panelH - 30

  const fo = panel.append("foreignObject")
      .attr("x", 10)
      .attr("y", 24)
      .attr("width", viewW)
      .attr("height", viewH)

  const div = fo.append("xhtml:div")
      .style("width", "100%")
      .style("height", "100%")
      .style("overflow", "auto")
      .style("font-size", "12px")

  const rows = div.selectAll(".row")
      .data(rawEvents)
      .enter()
      .append("div")
      .style("display", "flex")
      .style("align-items", "center")
      .style("gap", "8px")
      .style("margin-bottom", "4px")

  // raw_event text
  rows.append("span")
      .text(d => d)
      .style("white-space", "nowrap")

}
</script>

<template>
  <div class="raw-first-view">
    <div class="raw-first-header">
      Raw Event → Semantic Node Mapping
    </div>

    <div class="raw-first-container">
      <svg ref="svgRef"></svg>
    </div>
  </div>
</template>

<style scoped>
.raw-first-view {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.raw-first-container {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* sticky header */
.raw-first-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: #ffffff;
  padding: 6px 10px;
  border-bottom: 1px solid #e5e7eb;
  font-size: 14px;
  font-weight: 600;
  color: #555;
  background: rgba(245,245,242);
}

/* only affect THIS component svg */
.raw-first-container svg {
  display: block;
  background: #fff;
}
</style>

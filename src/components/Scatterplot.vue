<script setup>
import { ref, watch } from "vue"
import * as d3 from "d3"
import { usePayloadStore } from "@/store/payloadStore"

const svgRef = ref(null)
const store = usePayloadStore()
const circleSelRef = ref(null)
const tooltipRef = ref(null)

watch(
    () => store.payload?.scatter_states,
    (data) => {
      if (data) render(data)
    },
    { immediate: true }
)

watch(
    () => store.selectedStates,   // 你的 store 里就是 Set
    (sel) => {
      const circleSel = circleSelRef.value
      if (!circleSel) return

      circleSel
          .attr("stroke", d => sel.has(d.state?.join("→")) ? "#000" : "none")
          .attr("stroke-width", d => sel.has(d.state?.join("→")) ? 2 : null)
          .attr("r", d => sel.has(d.state?.join("→")) ? 7 : 4)
          .attr("opacity", d => sel.size === 0 ? 0.8 : (sel.has(d.state?.join("→")) ? 1 : 0.15))
    },
    { deep: false, immediate: true }
)

function showTooltip(html, event) {
  const svg = d3.select(svgRef.value)
  const [x, y] = d3.pointer(event, svg.node())

  const el = d3.select(tooltipRef.value)
  el.html(html)
      .style("left", (x + 12) + "px")
      .style("top", (y + 12) + "px")
      .style("opacity", 1)
}

function hideTooltip() {
  d3.select(tooltipRef.value).style("opacity", 0)
}


function render(data) {

  const svg = d3.select(svgRef.value)
  svg.selectAll("*").remove()

  const width = svgRef.value.clientWidth
  const height = svgRef.value.clientHeight

  const margin = 30

  const points = data

  // ========== scales ==========
  const xScale = d3.scaleLinear()
      .domain(d3.extent(points, d => d.x))
      .range([margin, width - margin])

  const yScale = d3.scaleLinear()
      .domain(d3.extent(points, d => d.y))
      .range([height - margin, margin])

  const tokens = store.payload?.legend?.tokens || []
  const placeholder = store.payload?.legend?.placeholder

  const domain = tokens.filter(t => t !== placeholder)

  const color = d3.scaleOrdinal()
      .domain(domain)
      .range(domain.map((_, i) => d3.schemeTableau10[i % 10]))


  // ========== zoom ==========
  const root = svg.append("g")

  svg.call(
      d3.zoom().scaleExtent([0.3, 8]).on("zoom", e => {
        root.attr("transform", e.transform)
      })
  )

  // ========== draw ==========
  const circleSel = root.selectAll("circle")
      .data(points, d => d.state?.join("→"))     // ✅ key function，避免重绘错位
      .join("circle")
      .attr("data-key", d => d.state?.join("→")) // ✅ 用于后续匹配
      .attr("cx", d => xScale(d.x))
      .attr("cy", d => yScale(d.y))
      .attr("r", 4)
      .attr("fill", d => color(d.state?.[d.state.length - 1]))
      .attr("opacity", 0.8)
      .on("mouseenter", (e, d) => {
        // 放大
        d3.select(e.currentTarget)
            .attr("r", 8)
            .attr("stroke", "#000")

        // tooltip 内容
        const label = d.state?.join(" → ")
        showTooltip(label, e)
      })
      .on("mousemove", (e) => {
        const svg = d3.select(svgRef.value)
        const [x, y] = d3.pointer(e, svg.node())

        d3.select(tooltipRef.value)
            .style("left", (x + 12) + "px")
            .style("top", (y + 12) + "px")
      })
      .on("mouseleave", (e, d) => {

        hideTooltip()

        const selected = store.selectedStates.has(d.state?.join("→"))

        d3.select(e.currentTarget)
            .attr("r", selected ? 7 : 4)
            .attr("stroke", selected ? "#000" : "none")
            .attr("stroke-width", selected ? 2 : null)
      })

      .on("click", (e, d) => {
        const stKey = d.state.join("→")
        // 一阶节点 = 高阶状态最后一个元素
        const cls = String(d.state[d.state.length - 1])
        store.toggleState(stKey, cls)   // ⭐关键
      })


  circleSelRef.value = circleSel

}

</script>

<template>
  <div class="scatter-container">
    <svg ref="svgRef"></svg>
    <div ref="tooltipRef" class="tooltip"></div>
  </div>
</template>

<style scoped>
.scatter-container {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: #ffffff;
}

svg {
  width: 100%;
  height: 100%;
}
.tooltip {
  position: absolute;
  pointer-events: none;
  background: rgba(0,0,0,0.75);
  color: #fff;
  padding: 4px 8px;
  font-size: 12px;
  border-radius: 4px;
  opacity: 0;
}


</style>

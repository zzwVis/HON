<script setup>
import { watch, computed } from "vue"
import * as d3 from "d3"
import { useBrushStore } from "@/store/brushStore.js"
const brushStore = useBrushStore()
import { useRegionStore } from "@/store/regionStore.js"
const regionStore = useRegionStore()
import { usePayloadStore } from "@/store/payloadStore.js"
const payloadStore = usePayloadStore()
import { ref, onMounted } from "vue"
import { nextTick } from "vue"

const treemapRef = ref(null)
const layoutWidth = ref(220)
const expanded = ref(new Set(["global"]))  // 默认展开 root

function toggleExpand(id) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
}


onMounted(async () => {
  await nextTick()

  if (treemapRef.value) {
    layoutWidth.value = treemapRef.value.clientWidth
  }
})

function collectIds(node, out = []) {
  out.push(node.id)

  if (node.children) {
    node.children.forEach(c => collectIds(c, out))
  }

  return out
}

function flattenTree(node, depth = 0, out = []) {
  out.push({
    id: node.id,
    name: node.name,
    depth,
    hasChildren: node.children?.length > 0
  })

  if (!expanded.value.has(node.id)) return out

  if (node.children) {
    node.children.forEach(c =>
        flattenTree(c, depth + 1, out)
    )
  }

  return out
}

const brushTreeList = computed(() => {
  return flattenTree(brushTreeRoot.value)
})

function statesByClass(b) {
  const glyph = payloadStore.payload?.glyph
  if (!glyph) {
    return { grouped: {}, ungrouped: [] }
  }

  const grouped = {}
  const usedStates = new Set()

  // 1️⃣ 先处理 class → states
  for (const cls of b.classes) {
    const states = glyph[cls]?.unique_states || []

    const selected = states
        .map(st => payloadStore.stateKey(st))
        .filter(k => b.states.has(k))

    if (selected.length) {
      grouped[cls] = selected
      selected.forEach(s => usedStates.add(s))
    }
  }

  // 2️⃣ 再找“没有被任何 class 吸收的 state”
  const ungrouped = Array.from(b.states)
      .filter(s => !usedStates.has(s))

  return { grouped, ungrouped }
}


function shorten(key) {
  // A->B 形式可直接显示
  return key
}

function activateBrush(id) {
  brushStore.setActiveBrush(id)
}

function sourceLabel(b) {
  const regions = Object.values(regionStore.regions)

  const r = regions.find(r => r.brushId === b.id)
  if (!r) return null

  // 没有来源
  if (!r.sourceBrushId) return null

  // 找来源的 brush
  const srcBrush = brushStore.brushes[r.sourceBrushId]

  return srcBrush ? srcBrush.name : "Global"
}

// 当刷子被删除的时候，她对应的视图也应该被删除
function removeBrushAndClear(bid) {
  brushStore.removeBrush(bid)
  regionStore.clearBrush(bid)
}

// ===== 基于 source 信息构造 brush 层次结构，并用矩形树图布局 =====
const brushTreeRoot = computed(() => {

  const brushes = brushStore.brushes
  const regions = regionStore.regions

  const nodes = {}

  for (const b of Object.values(brushes)) {
    nodes[b.id] = {
      id: b.id,
      name: b.name,
      children: []
    }
  }

  const root = {
    id: "global",
    name: "Global",
    children: []
  }

  for (const b of Object.values(brushes)) {

    const r = Object.values(regions).find(r => r.brushId === b.id)

    if (!r || r.sourceBrushId == null) continue

    const src = r.sourceBrushId

    if (src === "global") {
      root.children.push(nodes[b.id])
    }
    else if (nodes[src]) {
      nodes[src].children.push(nodes[b.id])
    }

  }

  return root   // ★ 关键
})

watch(
    () => brushTreeRoot.value,
    (root) => {
      if (!root) return

      const ids = collectIds(root)

      expanded.value = new Set(ids)
    },
    { immediate: true }
)

</script>

<template>
  <div class="brush-panel">
    <!-- 矩形树图展示 brush 之间的层次结构 -->
    <div class="brush-tree">

      <div
          v-for="node in brushTreeList"
          :key="node.id"
          class="tree-row"
          :style="{ paddingLeft: (node.depth * 14) + 'px' }"
      >

        <!-- 展开按钮 -->
        <span
            v-if="node.hasChildren"
            class="toggle"
            :class="{ expanded: expanded.has(node.id) }"
            @click.stop="toggleExpand(node.id)"
        >
          <svg
              class="arrow-icon"
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
          >
            <path
                d="M4 2L8 6L4 10"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
            />
          </svg>
        </span>

        <span
            v-else
            class="toggle-placeholder"
        />

        <!-- 颜色点 -->
        <span
            v-if="node.id !== 'global'"
            class="dot"
            :style="{background: brushStore.brushes[node.id]?.color}"
        />

        <!-- 名字 -->
        <span
            class="tree-name"
            @click="node.id !== 'global' && activateBrush(node.id)"
        >
      {{ brushStore.brushes[node.id]?.name || node.name }}
    </span>

      </div>

    </div>

    <div style = "border: 1px solid #c0c0c0;height: 100%">
      <button class="new-btn"
              @click="brushStore.createBrush()">
        + New Filter
      </button>

      <div
          v-for="b in Object.values(brushStore.brushes)"
          :key="b.id"
          class="brush-card"
          :class="{ active: b.id === brushStore.activeBrushId }"
      >

        <!-- 顶部栏 -->
        <div class="brush-header"
             @click="activateBrush(b.id)">

          <span class="dot"
                :style="{background:b.color}">
          </span>

          <span class="name">{{ b.name }}</span>
          <span v-if="sourceLabel(b)" class="name">
            source: {{ sourceLabel(b) }}
          </span>

          <!--          <span class="count">-->
          <!--            ({{ b.edges.length }} sequences)-->
          <!--          </span>-->

          <button class="del"
                  @click.stop="removeBrushAndClear(b.id)">
            ✕
          </button>
        </div>

        <!-- 按 class 分组的状态列表 -->
        <div v-if="b.classes && b.classes.size" class="section-block">
          <div class="class-title">
            nodes:
          </div>
          <div
              v-for="(cls, i) in b.classes"
              :key="cls"
              class="class-block"
          >
            <div class="state-item">
              {{ i + 1 }}. node {{ cls }}
            </div>

            <!--        <div-->
            <!--            v-for="(s,i) in states"-->
            <!--            :key="s"-->
            <!--            class="state-item"-->
            <!--        >-->
            <!--          {{ i+1 }}. {{ shorten(s) }}-->
            <!--        </div>-->

          </div>
        </div>

        <!-- 没有归属 class 的 state -->
        <div
            v-if="statesByClass(b).ungrouped.length > 0"
            class="class-block ungrouped"
        >
          <div class="class-title">
            states:
          </div>

          <div
              v-for="(s, i) in statesByClass(b).ungrouped"
              :key="s"
              class="state-item"
          >
            {{ i + 1 }}. {{ shorten(s) }}
          </div>
        </div>

        <!-- 边列表 -->
        <div v-if="b.edges && b.edges.length > 0" class="section-block">
          <div class="section-title">
            edges:
          </div>

          <div
              v-for="(e, i) in b.edges"
              :key="e"
              class="section-item edge-item"
          >
            {{ i + 1 }}. {{ shorten(e) }}
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.brush-panel {
  width: 220px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 15px;
}

.new-btn {
  width: 100%;
  padding: 4px;
  background: #f6f6f6;
  font-weight: 600;
  color: #555;
  border: 1px solid #dcdfe6;
  transition: all 0.2s ease;
  margin: 4px
}

.brush-card {
  border: 1px solid #ccc;
  border-radius: 4px;
  overflow: hidden;
  margin-left: 4px;
  margin-right: 4px;
}

.brush-card.active {
  border:2px solid #4a90e2;
}

.brush-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  cursor: pointer;
  background: #f7f7f7;
}

.brush-header:hover {
  background: #ececec;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.name {
  flex: 1;
}

.count {
  color: #888;
}

.del {
  border: none;
  background: none;
  cursor: pointer;
  color: #c00;
}

.edge-item {
  font-size: 15px;
  color: #333;
}

.state-item {
  font-size: 14px;
  color: #333;
}

.class-block {
  padding: 6px 10px;
  background: #fafafa;
}

.class-title {
  font-weight: 600;
  color: #333;
  margin-bottom: 4px;
}

.state-item {
  font-size: 14px;
  padding-left: 12px;
  color: #555;
}

.section-block {
  padding: 6px 10px;
  background: #fafafa;
  border-top: 1px dashed #e0e0e0;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #333;
  margin-bottom: 4px;
  text-transform: lowercase;
}

.dot {
  width:10px;
  height:10px;
  border-radius:50%;
}

.brush-tree {
  border: 1px solid #e4e7ed;
  position: relative;
  height: 30%;
  background: white;
  width: 100%;
  border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
  transition: all 0.2s ease;
  overflow-y: auto;
  overflow-x: hidden;  /* 隐藏水平滚动条 */
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  padding: 0 8px;
  margin-left: 5px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s ease;
  position: relative;
  /* 确保文字左对齐 */
  text-align: left;
  justify-content: flex-start; /* 水平方向从左开始 */
}

.tree-row:last-child {
  border-bottom: none;
}

.tree-row:hover {
  background: #f5f9ff;
  transform: translateX(2px);
}

/* 添加选中状态 */
.tree-row.active {
  background: #e9f0fe;
  border-left: 3px solid #4a90e2;
}

.tree-row .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  flex-shrink: 0;
}

.tree-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #2c3e50;
  font-weight: 500;
  font-size: 15px;
  flex: 1;
}

/* 添加层级线条 */
.tree-row {
  position: relative;
}

.tree-row::after {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: transparent;
  transition: background 0.2s;
}

.tree-row:hover::after {
  background: #4a90e2;
}

.toggle {
  width: 14px;
  display: inline-block;
  text-align: center;
  cursor: pointer;
  color: #333;
}

.toggle-placeholder {
  width: 14px;
  display: inline-block;
}
</style>
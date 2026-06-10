<script setup>
import GraphGlyph from "@/components/GraphGlyph.vue";
import DetailedHONode from "./components/DetailedHONode.vue";
import DetailedVONode from "./components/DetailedVONode.vue";
import Scatterplot from "./components/Scatterplot.vue";
import Sequence from "@/components/Sequence.vue";
import RawSequence from "@/components/RawSequence.vue";
import BrushPanel from "@/components/BrushPanel.vue";
import Comparison from "@/components/Comparison.vue";
import { useRegionStore } from "@/store/regionStore.js"

const regionStore = useRegionStore()
</script>

<template>
  <div class="container">
    <!-- 左列 -->
    <div class="left-column">
      <div class="cell top-left">
<!--        <DetailedVONode />-->
      </div>
      <div class="cell bottom-left">
        <DetailedHONode />
      </div>
    </div>

    <!-- 中列 -->
    <div class="middle-column">
      <div class="grid-container">
        <div class="grid-cell top-left" :class="{ 'container-active': regionStore.activeRegionId === 'global' }">
          <GraphGlyph />
        </div>
        <div class="grid-cell top-right">
          <RawSequence />
<!--          <Sequence />-->
        </div>
        <!-- 合并底部区域 -->
        <div class="grid-cell bottom-full">
          <Comparison />
        </div>
      </div>
    </div>

    <!-- 右列 -->
    <div class="right-column">
<!--      <div class="cell top-right">-->
<!--        <Scatterplot />-->
<!--      </div>-->
      <div class="cell bottom-right">
        <BrushPanel />
      </div>
    </div>
  </div>
</template>

<style scoped>
.container {
  position: absolute;
  display: flex;
  height: 100vh;
  width: 100vw;
  left: 0;
  top: 0;
  gap: 12px;
  padding: 12px;
  box-sizing: border-box;
  background: var(--paper-bg);
}

/* 三列的通用样式 */
.left-column,
.middle-column,
.right-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 12px;
}

/* 左列 */
.left-column {
  flex: 2.15;
  min-width: 0;
}

/* 中列 */
.middle-column {
  flex: 11;
  min-width: 0;
  border: 1px solid var(--panel-border);
  border-radius: 7px;
  background-color: var(--panel-bg);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
  padding: 9px;
}

/* 右列：占2/6宽度 */
.right-column {
  flex: 2.1;
  min-width: 0;
}

/* 单元格通用样式 */
.cell {
  position: relative;
  min-height: 0;
  border: 1px solid var(--panel-border);
  border-radius: 7px;
  background-color: var(--panel-bg);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
}

.left-column .bottom-left {
  flex: 1; /* 占满整个空间 */
  min-height: 0;
}

/* 如果 top-left 被移除，可以删除这个样式 */
.left-column .top-left {
  display: none; /* 或者完全删除这个样式 */
}

/* 右列布局 - 使用8行布局（2+6） */
.right-column {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.right-column .bottom-right {
  flex: 1; /* 占6行 */
  min-height: 0;
}

/* 中列网格容器 - 修改为2x2布局，底部合并为一行 */
.grid-container {
  display: grid;
  grid-template-columns: minmax(360px, 3fr) minmax(520px, 5fr);
  grid-template-rows: minmax(310px, 2fr) minmax(420px, 3fr);
  gap: 9px;
  height: 100%;
  width: 100%;
  box-sizing: border-box;
}

/* 网格单元格 */
.grid-cell {
  position: relative;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background-color: var(--panel-bg);
  overflow: hidden;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
}

.grid-cell::before,
.cell::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: inherit;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

/* 合并底部区域 - 新增样式 */
.grid-cell.bottom-full {
  grid-column: 1 / 3; /* 跨越第1列到第3列（整行） */
  grid-row: 2; /* 第二行 */
}

/* 确保内部组件自适应容器大小 */
.cell > * {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
}

.grid-cell > * {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
}

.top-right{
  background-color: var(--panel-bg);
}

.bottom-right {
  border: 1px solid var(--panel-border);
  background: var(--panel-bg);
}


/* 响应式调整 */
@media (max-width: 1200px) {
  .container {
    flex-direction: column;
  }

  .left-column,
  .middle-column,
  .right-column {
    width: 100%;
    flex: none;
    height: auto;
  }

  /* 响应式时恢复普通布局 */
  .grid-container {
    grid-template-columns: 1fr;
    grid-template-rows: repeat(3, 1fr);
  }

  .grid-cell.bottom-full {
    grid-column: 1;
    grid-row: 3;
  }
}

.container-active {
  border-color: rgba(47, 111, 159, 0.65);
  box-shadow: 0 0 0 2px rgba(47, 111, 159, 0.12), var(--shadow-soft);
  transform: translateY(-1px);
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

</style>

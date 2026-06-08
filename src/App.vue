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
  gap: 16px;
  padding: 8px;
  box-sizing: border-box;
}

/* 三列的通用样式 */
.left-column,
.middle-column,
.right-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 16px;
}

/* 左列 */
.left-column {
  flex: 2;
  min-width: 0;
}

/* 中列 */
.middle-column {
  flex: 11;
  min-width: 0;
  border: 1px solid #c0c0c0;
  border-radius: 4px;
  background-color: #ffffff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  overflow: hidden;
  padding: 8px;
}

/* 右列：占2/6宽度 */
.right-column {
  flex: 2;
  min-width: 0;
}

/* 单元格通用样式 */
.cell {
  min-height: 0;
  border: 1px solid #c0c0c0;
  border-radius: 4px;
  background-color: #ffffff;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
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
  gap: 16px;
}

.right-column .bottom-right {
  flex: 1; /* 占6行 */
  min-height: 0;
}

/* 中列网格容器 - 修改为2x2布局，底部合并为一行 */
.grid-container {
  display: grid;
  grid-template-columns: 3fr 5fr; /* 2列 */
  grid-template-rows: 2fr 3fr; /* 2行，但底部单元格将占据整行 */
  gap: 8px; /* 网格之间的间隙 */
  height: 100%;
  width: 100%;
  box-sizing: border-box;
}

/* 网格单元格 */
.grid-cell {
  border: 1px solid black;
  border-radius: 4px;
  background-color: #f8f8f8;
  overflow: hidden;
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
  background-color: #ffffff;
}

.bottom-right {
  border: none;
  background: white;
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
  transform: scale(1.01);
  box-shadow: 0 6px 18px rgba(0,0,0,0.20);
}

</style>
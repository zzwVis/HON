<script setup>
import GraphGlyph from "@/components/GraphGlyph.vue";
import RawSequence from "@/components/RawSequence.vue";
import BrushPanel from "@/components/BrushPanel.vue";
import Comparison from "@/components/Comparison.vue";
import FirstOrderStateInspector from "@/components/FirstOrderStateInspector.vue";
import GlobalLegend from "@/components/GlobalLegend.vue";
import { useRegionStore } from "@/store/regionStore.js"

const regionStore = useRegionStore()
</script>

<template>
  <div class="container">
    <div class="workspace-column">
      <GlobalLegend />
      <div class="workspace-grid">
        <div class="grid-cell first-order-view">
          <RawSequence fixed-mode="graph" />
        </div>

        <div class="grid-cell higher-order-view" :class="{ 'container-active': regionStore.activeRegionId === 'global' }">
          <GraphGlyph />
        </div>

        <div class="grid-cell sequence-view">
          <RawSequence :modes="['sequence', 'sankey']" initial-mode="sankey" />
        </div>

        <div class="grid-cell inspector-view">
          <FirstOrderStateInspector />
<!--          <DetailedHONode />-->
        </div>

        <div class="grid-cell comparison-view">
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

/* 主工作区 + 右侧面板 */
.workspace-column,
.right-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 12px;
}

/* 主工作区 */
.workspace-column {
  flex: 12.8;
  min-width: 0;
  display: flex;
  flex-direction: column;
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

.workspace-grid {
  display: grid;
  flex: 1;
  grid-template-columns: minmax(220px, 1.85fr) minmax(360px, 3.2fr) minmax(460px, 5fr);
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

.first-order-view {
  grid-column: 1;
  grid-row: 1;
}

.higher-order-view {
  grid-column: 2;
  grid-row: 1;
}

.sequence-view {
  grid-column: 3;
  grid-row: 1;
}

.inspector-view {
  grid-column: 1;
  grid-row: 2;
}

.comparison-view {
  grid-column: 2 / 4;
  grid-row: 2;
}

/* 确保内部组件自适应容器大小 */
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

  .workspace-column,
  .right-column {
    width: 100%;
    flex: none;
    height: auto;
  }

  /* 响应式时恢复普通布局 */
  .workspace-grid {
    grid-template-columns: 1fr;
    grid-template-rows: repeat(5, minmax(280px, 1fr));
  }

  .first-order-view,
  .higher-order-view,
  .sequence-view,
  .inspector-view,
  .comparison-view {
    grid-column: 1;
  }

  .first-order-view {
    grid-row: 1;
  }

  .higher-order-view {
    grid-row: 2;
  }

  .sequence-view {
    grid-row: 3;
  }

  .inspector-view {
    grid-row: 4;
  }

  .comparison-view {
    grid-row: 5;
  }
}

.container-active {
  border-color: rgba(47, 111, 159, 0.65);
  box-shadow: 0 0 0 2px rgba(47, 111, 159, 0.12), var(--shadow-soft);
  transform: translateY(-1px);
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

</style>

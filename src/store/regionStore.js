// store/regionStore.js
import { defineStore } from "pinia"
import { reactive } from "vue"

let rid = 0

// 统一的 Region 创建函数（非常关键）
function createRegion({
                          id,
                          brushId = null,
                          prev = 0,
                          next = 0,
                          sequences = [],
                          sequenceIds = null,
                          // ⭐ 新增：窗口截断前的 base 子集（用于继续过滤）
                          baseRawSeqs = null,
                          baseTokenSeqs = null,
                          applied = false,   // ⭐ 新增
                          // ⭐ 新增
                          sourceRegionId = null,
                          sourceBrushId = null,
                          sliceMode= false,  // ⭐ 默认不选中（原始模式）\
                          highlightNodes = null,   // ⭐ Set 或 null
                          highlightEdges = null,   // ⭐ Set 或 null
                      } = {}) {
    return { id,
        brushId,
        prev,
        next,
        sequences,
        sequenceIds,
        baseRawSeqs,
        baseTokenSeqs,
        applied,
        // ⭐ 新增
        sourceRegionId,
        sourceBrushId,
        sliceMode,
        highlightNodes,
        highlightEdges,
    }
}


export const useRegionStore = defineStore("region", {
    state: () => ({
        regions: {
            // ⭐ 全量图 region
            global: createRegion({
                id: "global",
                brushId: null,
                prev: 0,
                next: 0,
                sequences: [],
                sequenceIds: null,
                baseRawSeqs: null,
                baseTokenSeqs: null,
                applied: false,
                sourceRegionId: null,
                sourceBrushId: null,
                sliceMode: false,
                highlightNodes: null,
                highlightEdges: null,
            }),

            // ⭐ Comparison 默认 region
            root: createRegion({
                id: "root",
                brushId: null,
                prev: 0,
                next: 0,
                sequences: [],
                sequenceIds: null,      // ⭐ 新增：这个 panel 绑定的序列 id 列表
                // ⭐ 新增：窗口截断前的 base 子集（用于继续过滤）
                baseRawSeqs: null,
                baseTokenSeqs: null,
                applied: false,   // ⭐ 新增
                // ⭐ root 没有来源
                sourceRegionId: null,
                sourceBrushId: null,
                sliceMode: false,  // ⭐ 默认不选中（原始模式）
                highlightNodes: null,
                highlightEdges: null,
            })
        },
        activeRegionId: "global"
    }),

    actions: {
        fork() {
            const base = this.regions[this.activeRegionId]
            const r = `r${++rid}`

            this.regions = {
                ...this.regions,
                [r]: {
                    id: r,
                    brushId: null,
                    prev: 0,
                    next: 0,
                    sequences: [],
                    sequenceIds: null,
                    baseRawSeqs: null,
                    baseTokenSeqs: null,

                    applied: false,
                    // ⭐ 新增：记录父 region
                    sourceRegionId: null,
                    sourceBrushId: null,
                    sliceMode: false,  // ⭐ 默认不选中（原始模式）
                    highlightNodes: null,
                    highlightEdges: null,
                }
                // 这是复制一个一样的
                // [r]: createRegion({
                //     id: r,
                //     brushId: base?.brushId ?? null,
                //     prev: base?.prev ?? 0,
                //     next: base?.next ?? 1,
                //     sequences: []   // fork 后重新计算
                // })
            }

            // this.activeRegionId = r
            // this.activeRegionId = null
            return r
        },

        setActive(regionId) {
            // 再点一次同一个 header → 取消选中
            if (this.activeRegionId === regionId) {
                this.activeRegionId = null
                return
            }
            if (this.regions[regionId]) {
                this.activeRegionId = regionId
            }
        },

        // actions 里新增
        setHighlightData(regionId, highlightNodes, highlightEdges) {
            const r = this.regions[regionId]
            if (!r) return
            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    highlightNodes,
                    highlightEdges,
                }
            }
        },

        // ⭐ 高性能版本（不替换整个 regions object）
        setHighlightDataFast(regionId, highlightNodes, highlightEdges) {
            const r = this.regions[regionId]
            if (!r) return

            r.highlightNodes = highlightNodes
            r.highlightEdges = highlightEdges
        },

        setBaseSequencesFast(regionId, rawSeqs, tokenSeqs, ids = null) {
            const r = this.regions[regionId]
            if (!r) return
            r.baseRawSeqs = Array.isArray(rawSeqs) ? rawSeqs : null
            r.baseTokenSeqs = Array.isArray(tokenSeqs) ? tokenSeqs : null
            r.sequenceIds = Array.isArray(ids) ? ids.slice() : null
        },

        setSourceInfo(regionId, sourceRegionId, sourceBrushId) {
            const r = this.regions[regionId]
            if (!r) return

            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    sourceRegionId,
                    sourceBrushId
                }
            }
        },
        // 把Comparison.vue算好的结果回写进region
        setSequences(regionId, sequences) {
            const r = this.regions[regionId]
            if (!r) return

            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    sequences
                }
            }
        },
                
        setBaseSequenceIds(regionId, ids) {   // ⭐ 新增
            const r = this.regions[regionId]
            if (!r) return

            this.regions = {
            ...this.regions,
            [regionId]: {
                ...r,
                sequenceIds: Array.isArray(ids) ? ids.slice() : null
            }
            }
        },

        setWindowBounds(regionId, prevMax, nextMax) {
            const r = this.regions[regionId]
            if (!r) return
            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    prevMax,
                    nextMax,
                    prev: Math.min(r.prev, prevMax),
                    next: Math.min(r.next, nextMax),
                }
            }
        },

        setBaseSequences(regionId, rawSeqs, tokenSeqs, ids = null) {
            const r = this.regions[regionId]
            if (!r) return
            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    baseRawSeqs: Array.isArray(rawSeqs) ? rawSeqs : null,
                    baseTokenSeqs: Array.isArray(tokenSeqs) ? tokenSeqs : null,
                    sequenceIds: Array.isArray(ids) ? ids.slice() : null   // ⭐ 新增
                }
            }
        },

        clearBaseSequences(regionId) {
            const r = this.regions[regionId]
            if (!r) return
            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    baseRawSeqs: null,
                    baseTokenSeqs: null,
                }
            }
        },

        assignBrush(regionId, brushId) {
            const r = this.regions[regionId]
            if (!r) return

            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    brushId,
                    sequences: []   // ⭐ 清空旧结果
                }
            }
        },

        replaceBrush(oldBrushId, newBrushId) {
            let changed = false
            const newRegions = {}

            for (const [id, r] of Object.entries(this.regions)) {
                if (r.brushId === oldBrushId) {
                    newRegions[id] = {
                        ...r,
                        brushId: newBrushId
                    }
                    changed = true
                } else {
                    newRegions[id] = r
                }
            }

            if (changed) this.regions = newRegions
        },

        remove(regionId) {
            // 1. root 不允许删
            if (regionId === "root") return

            const newRegions = { ...this.regions }
            delete newRegions[regionId]

            // 2. 如果删的是 active
            if (this.activeRegionId === regionId) {
                const ids = Object.keys(newRegions)
                this.activeRegionId = ids.length ? ids[0] : "root"
            }

            // 3. 至少留一个 region
            if (Object.keys(newRegions).length === 0) {
                newRegions["root"] = createRegion({ id: "root" })
                this.activeRegionId = "root"
            }

            this.regions = newRegions
        },

        clearBrush(brushId) {
            let changed = false
            const newRegions = {}

            for (const [id, r] of Object.entries(this.regions)) {
                if (r.brushId === brushId) {
                    newRegions[id] = {
                        ...r,
                        brushId: null,
                        sequences: [],
                        sequenceIds: null        // ⭐ 新增
                    }
                    changed = true
                } else {
                    newRegions[id] = r
                }
            }

            if (changed) {
                this.regions = newRegions
            }
        },
        applyRegion(regionId) {
            const r = this.regions[regionId]
            if (!r) return

            this.regions = {
                ...this.regions,
                [regionId]: {
                    ...r,
                    applied: true
                }
            }
        }
    }
})

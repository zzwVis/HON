// store/regionStore.js
import { defineStore } from "pinia"
import { reactive } from "vue"
import { apiUrl } from "@/api"

let rid = 0

// 统一的 Region 创建函数（非常关键）
function createRegion({
                          id,
                          brushId = null,
                          prev = 0,
                          next = 0,
                          sequences = [],
                          sequenceIds = null,
                          globalSeqIds = null,
                          // ⭐ 新增：窗口截断前的 base 子集（用于继续过滤）
                          baseRawSeqs = null,
                          baseTokenSeqs = null,
                          applied = false,   // ⭐ 新增
                          // ⭐ 新增
                          sourceRegionId = null,
                          sourceBrushId = null,
                          sliceMode= false,  // ⭐ 默认不选中（原始模式）\
                          sliceAnchor = null,
                          highlightNodes = null,   // ⭐ Set 或 null
                          highlightEdges = null,   // ⭐ Set 或 null
                          modelPayload = null,
                          modelStatus = "none",
                          modelError = null,
                          modelInfo = null,
                          modelResetSnapshot = null,
                      } = {}) {
    return { id,
        brushId,
        prev,
        next,
        sequences,
        sequenceIds,
        globalSeqIds,
        baseRawSeqs,
        baseTokenSeqs,
        applied,
        // ⭐ 新增
        sourceRegionId,
        sourceBrushId,
        sliceMode,
        sliceAnchor,
        highlightNodes,
        highlightEdges,
        modelPayload,
        modelStatus,
        modelError,
        modelInfo,
        modelResetSnapshot,
    }
}

function cloneSeqs(seqs) {
    return Array.isArray(seqs)
        ? seqs.map(seq => Array.isArray(seq) ? seq.slice() : seq)
        : []
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
                globalSeqIds: null,
                baseRawSeqs: null,
                baseTokenSeqs: null,
                applied: false,
                sourceRegionId: null,
                sourceBrushId: null,
                sliceMode: false,
                sliceAnchor: null,
                highlightNodes: null,
                highlightEdges: null,
                modelPayload: null,
                modelStatus: "none",
                modelError: null,
                modelInfo: null,
            }),

            // ⭐ Comparison 默认 region
            root: createRegion({
                id: "root",
                brushId: null,
                prev: 0,
                next: 0,
                sequences: [],
                sequenceIds: null,      // ⭐ 新增：这个 panel 绑定的序列 id 列表
                globalSeqIds: null,
                // ⭐ 新增：窗口截断前的 base 子集（用于继续过滤）
                baseRawSeqs: null,
                baseTokenSeqs: null,
                applied: false,   // ⭐ 新增
                // ⭐ root 没有来源
                sourceRegionId: null,
                sourceBrushId: null,
                sliceMode: false,  // ⭐ 默认不选中（原始模式）
                sliceAnchor: null,
                highlightNodes: null,
                highlightEdges: null,
                modelPayload: null,
                modelStatus: "none",
                modelError: null,
                modelInfo: null,
            })
        },
        activeRegionId: "global",
        overlay: {
            baseRegionId: null,
            targetRegionId: null
        }
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
                    globalSeqIds: null,
                    baseRawSeqs: null,
                    baseTokenSeqs: null,

                    applied: false,
                    // ⭐ 新增：记录父 region
                    sourceRegionId: null,
                    sourceBrushId: null,
                    sliceMode: false,  // ⭐ 默认不选中（原始模式）
                    sliceAnchor: null,
                    highlightNodes: null,
                    highlightEdges: null,
                    modelPayload: null,
                    modelStatus: "none",
                    modelError: null,
                    modelInfo: null,
                    modelResetSnapshot: null,
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
            r.globalSeqIds = Array.isArray(ids) ? ids.slice() : null
            r.modelPayload = null
            r.modelStatus = "none"
            r.modelError = null
            r.modelInfo = null
            r.modelResetSnapshot = null
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
                sequenceIds: Array.isArray(ids) ? ids.slice() : null,
                globalSeqIds: Array.isArray(ids) ? ids.slice() : null
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
                    sequenceIds: Array.isArray(ids) ? ids.slice() : null,   // ⭐ 新增
                    globalSeqIds: Array.isArray(ids) ? ids.slice() : null,
                    modelPayload: null,
                    modelStatus: "none",
                    modelError: null,
                    modelInfo: null,
                    modelResetSnapshot: null,
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
                    sequences: [],   // ⭐ 清空旧结果
                    sliceAnchor: null,
                    modelPayload: null,
                    modelStatus: "none",
                    modelError: null,
                    modelInfo: null,
                    modelResetSnapshot: null,
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

        setOverlay(baseRegionId, targetRegionId) {
            if (!baseRegionId || !targetRegionId) return
            if (baseRegionId === targetRegionId) return
            if (!this.regions[baseRegionId] || !this.regions[targetRegionId]) return

            this.overlay = {
                baseRegionId,
                targetRegionId
            }
        },

        clearOverlay() {
            this.overlay = {
                baseRegionId: null,
                targetRegionId: null
            }
        },

        remove(regionId) {
            // 1. root 不允许删
            if (regionId === "root") return

            const newRegions = { ...this.regions }
            delete newRegions[regionId]

            if (
                this.overlay.baseRegionId === regionId ||
                this.overlay.targetRegionId === regionId
            ) {
                this.clearOverlay()
            }

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
                        sequenceIds: null,        // ⭐ 新增
                        globalSeqIds: null,
                        modelPayload: null,
                        modelStatus: "none",
                        modelError: null,
                        modelInfo: null,
                        modelResetSnapshot: null,
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

        removeRegionsByBrush(brushId) {
            const newRegions = {}
            let changed = false

            for (const [id, r] of Object.entries(this.regions)) {
                if (id !== "global" && id !== "root" && r.brushId === brushId) {
                    changed = true
                    continue
                }
                newRegions[id] = r
            }

            if (!changed) return

            if (
                this.overlay.baseRegionId &&
                !newRegions[this.overlay.baseRegionId]
            ) {
                this.clearOverlay()
            }
            if (
                this.overlay.targetRegionId &&
                !newRegions[this.overlay.targetRegionId]
            ) {
                this.clearOverlay()
            }

            if (!newRegions[this.activeRegionId]) {
                this.activeRegionId = newRegions.global ? "global" : Object.keys(newRegions)[0] || "root"
            }

            this.regions = newRegions
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
        },

        async rebuildRegionModel(regionId, options = {}) {
            const r = this.regions[regionId]
            const sourceSeqIds = Array.isArray(r?.globalSeqIds) && r.globalSeqIds.length > 0
                ? r.globalSeqIds
                : r?.sequenceIds
            const sliceSequences = Array.isArray(options.firstOrderSequences)
                ? options.firstOrderSequences.filter(seq => Array.isArray(seq) && seq.length > 0)
                : null
            if (!r || ((!Array.isArray(sourceSeqIds) || sourceSeqIds.length === 0) && !sliceSequences?.length)) return null

            const resetSnapshot = {
                sequenceIds: Array.isArray(sourceSeqIds) ? sourceSeqIds.slice() : [],
                globalSeqIds: Array.isArray(sourceSeqIds) ? sourceSeqIds.slice() : [],
                sequences: cloneSeqs(r.sequences),
                slicedFirstOrderSequences: cloneSeqs(r.slicedFirstOrderSequences),
                baseRawSeqs: cloneSeqs(r.baseRawSeqs),
                baseTokenSeqs: cloneSeqs(r.baseTokenSeqs),
                sliceMode: Boolean(r.sliceMode),
                sliceAnchor: r.sliceAnchor ?? null,
                prev: r.prev,
                next: r.next,
                prevMax: r.prevMax ?? 0,
                nextMax: r.nextMax ?? 0,
            }

            r.modelStatus = "running"
            r.modelError = null

            try {
                const res = await fetch(apiUrl("/api/rebuild_region_model"), {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        seq_ids: sourceSeqIds,
                        first_order_sequences: sliceSequences,
                        n_clusters: options.nClusters ?? null,
                        K: options.K ?? 3,
                        refine_steps: options.refineSteps ?? 4
                    })
                })

                const data = await res.json().catch(() => ({}))
                if (!res.ok) {
                    throw new Error(data.detail || data.error || "Re-aggregate failed")
                }

                r.modelPayload = data
                r.modelInfo = data.model_info || null
                r.modelStatus = "ready"
                r.modelError = null
                r.modelResetSnapshot = resetSnapshot
                r.sequences = data.raw_sequences || []
                r.baseRawSeqs = data.raw_sequences || []
                r.baseTokenSeqs = data.first_order_sequences || []
                r.sequenceIds = (data.raw_sequences || []).map((_, index) => index)
                r.globalSeqIds = sourceSeqIds.slice()
                return data
            } catch (err) {
                r.modelStatus = "error"
                r.modelError = err?.message || String(err)
                return null
            }
        },

        resetRegionModel(regionId, payload = null) {
            const r = this.regions[regionId]
            if (!r) return

            const ids = Array.isArray(r.globalSeqIds) && r.globalSeqIds.length > 0
                ? r.globalSeqIds.slice()
                : (Array.isArray(r.sequenceIds) ? r.sequenceIds.slice() : [])
            const fullRaw = payload?.raw_sequences || []
            const fullTok = payload?.first_order_sequences || []
            const snapshot = r.modelResetSnapshot

            r.modelPayload = null
            r.modelStatus = "none"
            r.modelError = null
            r.modelInfo = null

            if (snapshot) {
                r.sequenceIds = Array.isArray(snapshot.sequenceIds) ? snapshot.sequenceIds.slice() : []
                r.globalSeqIds = Array.isArray(snapshot.globalSeqIds) ? snapshot.globalSeqIds.slice() : r.sequenceIds.slice()
                r.sliceMode = Boolean(snapshot.sliceMode)
                r.sliceAnchor = snapshot.sliceAnchor ?? null
                r.prev = snapshot.prev ?? r.prev
                r.next = snapshot.next ?? r.next
                r.prevMax = snapshot.prevMax ?? r.prevMax
                r.nextMax = snapshot.nextMax ?? r.nextMax
                r.sequences = cloneSeqs(snapshot.sequences)
                r.slicedFirstOrderSequences = cloneSeqs(snapshot.slicedFirstOrderSequences)
                r.baseRawSeqs = cloneSeqs(snapshot.baseRawSeqs)
                r.baseTokenSeqs = cloneSeqs(snapshot.baseTokenSeqs)
                r.modelResetSnapshot = null
                return
            }

            r.sequenceIds = ids
            r.globalSeqIds = ids.slice()
            r.baseRawSeqs = ids.map(id => fullRaw[id]).filter(Boolean)
            r.baseTokenSeqs = ids.map(id => fullTok[id]).filter(Boolean)
            r.sequences = []
            r.slicedFirstOrderSequences = []
            r.modelResetSnapshot = null
        }
    }
})

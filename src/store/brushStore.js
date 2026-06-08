import { defineStore } from "pinia"
import {computed, ref} from "vue"
import * as d3 from "d3"

import { usePayloadStore } from "@/store/payloadStore"
import { useRegionStore } from "@/store/regionStore"

function parseEdgePairs(edgesObjOrArr) {
    const edges = Array.isArray(edgesObjOrArr)
        ? edgesObjOrArr
        : Object.values(edgesObjOrArr || {})

    return edges
        .filter(Boolean)
        .map(e => {
            const [s, t] = e.split("→").map(d => d.trim())
            const sid = parseInt(s.replace("node", ""))
            const tid = parseInt(t.replace("node", ""))
            return [sid, tid]
        })
}

function findEdgeFirstIndices(seq, edgePairs) {
    const result = []

    for (const [a, b] of edgePairs) {
        let found = -1
        for (let i = 0; i < seq.length - 1; i++) {
            if (seq[i] === a && seq[i + 1] === b) {
                found = i
                break
            }
        }
        if (found === -1) return null
        result.push({ edge: [a, b], idx: found })
    }

    return result
}

function syncClassesFromStates(b) {
    const payloadStore = usePayloadStore()
    const glyph = payloadStore.payload?.glyph
    if (!glyph) return

    const nextClasses = new Set()

    for (const [cls, g] of Object.entries(glyph)) {
        const states = g.unique_states || []
        if (
            states.length > 0 &&
            states.every(st => b.states.has(payloadStore.stateKey(st)))
        ) {
            nextClasses.add(String(cls))
        }
    }

    b.classes = nextClasses
}

// ===== 下面这些工具函数，建议直接拷贝自你 RegionPanel 里的版本，保持一致 =====
function edgesToNodeSeq(edges) {
    if (!edges || edges.length === 0) return []
    const nodes = []
    edges.forEach((e, i) => {
        const [s, t] = e.split("→").map(d => d.trim())
        const sid = parseInt(s.replace("node", ""))
        const tid = parseInt(t.replace("node", ""))
        if (i === 0) nodes.push(sid)
        nodes.push(tid)
    })
    return nodes
}

function findSubsequenceIndex(seq, pattern) {
    if (!pattern || pattern.length === 0) return -1
    for (let i = 0; i <= seq.length - pattern.length; i++) {
        let ok = true
        for (let j = 0; j < pattern.length; j++) {
            if (seq[i + j] !== pattern[j]) { ok = false; break }
        }
        if (ok) return i
    }
    return -1
}

function normalizeStateKey(k) {
    return String(k).replace(/[()']/g, "").trim()
}

function hasClassMatchOnTokenSeq(tok, b) {
    if (!tok || !b) return false

    // 将tok转换为数组（处理代理对象）
    const tokenArray = Array.isArray(tok) ? tok : [...tok];
    const tokenSet = new Set(tokenArray.map(String)); // 转换为字符串Set以便快速查找

    // 将b转换为数组
    const classSet = b instanceof Set ?
        Array.from(b) :
        Object.values(b);

    // 检查classSet中的每个元素是否都在tokenSet中
    const result = classSet.every(item => tokenSet.has(item));

    return result;
}

// 只判断“是否存在 state 命中”，不做 window 切割
function hasStateMatchOnTokenSeq(seq, stateSet) {
    if (!seq || !stateSet || stateSet.size === 0) return false
    const tokens = seq.map(x => String(x).replace(/[()']/g, "").trim())
    const normalizedStateSet = new Set([...stateSet].map(normalizeStateKey))

    for (let i = 0; i < tokens.length; i++) {
        for (let j = i + 1; j <= tokens.length; j++) {
            const key = tokens.slice(i, j).join("→")
            if (normalizedStateSet.has(normalizeStateKey(key))) return true
        }
    }
    return false
}

export const useBrushStore = defineStore("brush", () => {
    // ⭐ 放在这里（store 初始化时执行一次）
    const payloadStore = usePayloadStore()
    const regionStore = useRegionStore()

    // 当前激活画笔
    const activeBrushId = ref(null)

    // ⭐ 新增：当前交互面板所属 region（全量图也算一个 region，例如 "root"）
    // 约定：全量图 panel 用 "root"（与你 regionStore 初始 root 一致）
    const activePanelRegionId = ref("root")

    // ⭐ 新增：可选，记录来源（方便 debug）
    // e.g. "global-graph" | "region-graph"
    const activePanelType = ref("global")

    const activeBrush = computed(() => {
        const id = activeBrushId.value
        return id ? brushes.value[id] : null
    })

    // brushId -> { id, name, color, edges: [] }
    const brushes = ref({})

    // ⭐ 新增：刷选的预览结果（还没写入 region）
    const preview = ref({
        targetRid: null,   // 要写入哪个 region（通常 = regionStore.activeRegionId）
        sourceRid: null,   // 数据来源 region（你刷的那张图）
        brushId: null,     // 用哪个 brush 得到的
        raw: null,         // 兼容旧字段；新逻辑按 seqIds 懒加载
        seqIds: null,   // ⭐ 新增
        tok: null,         // 兼容旧字段；新逻辑按 seqIds 懒加载
        count: 0,
        updatedAt: 0
    })

    // ⭐ 新增：sequence 索引缓存
    const sequenceIndexCache = ref({
        built: false,
        edgeToSeqIds: new Map(),
        stateToSeqIds: new Map(),
        classToSeqIds: new Map(),
        seqHighlights: new Map(),
    })

    // ---------- helpers ----------

    function ensureSequenceIndex() {

        const payloadStore = usePayloadStore()
        const rawSeqs = payloadStore.payload?.raw_sequences || []
        const tokSeqs = payloadStore.payload?.first_order_sequences || []

        if (sequenceIndexCache.value.built) return

        const edgeToSeqIds = new Map()
        const stateToSeqIds = new Map()
        const seqHighlights = new Map()
        const classToSeqIds = new Map()   // ⭐ 新增

        for (let sid = 0; sid < rawSeqs.length; sid++) {

            const raw = rawSeqs[sid]
            const tok = tokSeqs[sid]

            const nodes = []
            const edges = []

            for (let i = 0; i < raw.length; i++) {

                const nodeKey = "node" + raw[i]
                nodes.push(nodeKey)

                if (i < raw.length - 1) {

                    const edgeKey = `node${raw[i]}→node${raw[i+1]}`
                    edges.push(edgeKey)

                    if (!edgeToSeqIds.has(edgeKey))
                        edgeToSeqIds.set(edgeKey,new Set())

                    edgeToSeqIds.get(edgeKey).add(sid)
                }
            }

            seqHighlights.set(sid,{
                nodes,
                edges
            })

            // ⭐ class index (node class → sequence ids)
            const classSet = new Set(raw.map(v => String(v)))

            classSet.forEach(cls => {

                if (!classToSeqIds.has(cls))
                    classToSeqIds.set(cls, new Set())

                classToSeqIds.get(cls).add(sid)

            })

            // state index
            const tokens = tok.map(x=>String(x).replace(/[()']/g,"").trim())

            for (let i=0;i<tokens.length;i++){

                let acc=tokens[i]

                if(!stateToSeqIds.has(acc))
                    stateToSeqIds.set(acc,new Set())

                stateToSeqIds.get(acc).add(sid)

                for (let j=i+1;j<tokens.length;j++){

                    acc+="→"+tokens[j]

                    if(!stateToSeqIds.has(acc))
                        stateToSeqIds.set(acc,new Set())

                    stateToSeqIds.get(acc).add(sid)
                }
            }
        }

        sequenceIndexCache.value={
            built:true,
            edgeToSeqIds,
            stateToSeqIds,
            classToSeqIds,   // ⭐ 新增
            seqHighlights
        }
    }

    function genId() {
        return "brush_" + Math.random().toString(36).slice(2,9)
    }

    let colorIndex = 0

    function randomColor() {
        const palette = d3.schemeTableau10
        const c = palette[colorIndex % palette.length]
        colorIndex++
        return c
    }

    function nextBrushIndex() {
        const used = new Set()

        Object.values(brushes.value).forEach(b => {
            const m = b.name?.match(/^Brush\s+(\d+)$/)
            if (m) used.add(Number(m[1]))
        })

        let i = 1
        while (used.has(i)) i++
        return i
    }

    function renumberBrushes() {
        const arr = Object.values(brushes.value)

        // 按创建时间排序，保证“谁先创建谁排前”
        arr.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0))

        // 统一改名为 Brush 1..K
        arr.forEach((b, i) => {
            b.name = `Filter ${i + 1}`
        })
    }

    // ---------- actions ----------
    // 选择可以选状态，或者选类，或者选节点
    function createBrush(name) {
        const id = genId()
        brushes.value[id] = {
            id,
            name: name ?? "New Filter",
            createdAt: Date.now(),   // ✅ 新增：用于稳定重排
            color: randomColor(),

            states: new Set(),
            classes: new Set(),
            edges: [],

            window: {
                prev: null,
                next: null,
                mode: "split"
            }
        }
        // ✅ 创建后也重排一下（保证名字从 1 开始紧凑）
        renumberBrushes()

        activeBrushId.value = id
    }

    function removeBrush(id) {
        delete brushes.value[id]
        // ✅ 删除后重排编号：Brush 1..K
        renumberBrushes()

        if (activeBrushId.value === id) {
            activeBrushId.value = Object.keys(brushes.value)[0] || null
        }
    }

    function clearBrushEdges(id) {
        if (brushes.value[id]) {
            brushes.value[id].edges = []
        }
    }

    function setActiveBrush(id) {
        // 再点一次同一个 brush → 取消激活
        if (activeBrushId.value === id) {
            activeBrushId.value = null
            return
        }

        // 先切换 activeBrushId
        activeBrushId.value = id

        // 如果这个 brush 绑定了某个 region，则自动把该 region 设为 activeRegion
        if (id) {
            const entries = Object.entries(regionStore.regions || {})
            const found = entries.find(([, r]) => r.brushId === id)
            if (found) {
                const [rid] = found
                regionStore.setActive(rid)
            }
        }
    }


    // ⭐ 新增：在 panel 交互前调用，告诉 store：这次刷选属于哪个 region
    // 例：全量图 panel：setActivePanelRegion("root","global")
    // 例：子图 panel：setActivePanelRegion(regionId,"region")
    function setActivePanelRegion(regionId = "root", type = "global") {
        activePanelRegionId.value = regionId ?? "root"
        activePanelType.value = type ?? "global"
    }

    // ⭐ 新增：一个便捷 getter：当前这次刷选要作用的 region
    const activeRegionForBrush = computed(() => activePanelRegionId.value)

    function updateSourceInfoForBrush(b, sourceRid) {
        const regionsEntries = Object.entries(regionStore.regions || {})
        const attached = regionsEntries.find(([, r]) => r.brushId === b.id)
        if (attached) {
            const [targetRidForInfo] = attached
            const sourceRegion = regionStore.regions[sourceRid]
            const sourceInfoValue =
                sourceRid === "global"
                    ? "global"
                    : (sourceRegion?.brushId ?? null)

            regionStore.setSourceInfo(
                targetRidForInfo,
                sourceRid,
                sourceInfoValue
            )
        }
    }

    function commitActiveBrushToRegionLocal() {

        ensureSequenceIndex()

        const b = activeBrush.value
        if (!b) return



        const cache = sequenceIndexCache.value

        const sourceRid = activePanelRegionId.value || "root"
        const sourceRegion = regionStore.regions[sourceRid]
        if (!sourceRegion) return

        const highlightNodes = new Set()
        const highlightEdges = new Set()

        const edges = b.edges || []
        const states = b.states
        const classes = b.classes

        const hasEdges = edges.length > 0
        const hasStates = states && states.size > 0
        const hasClasses = classes && classes.size > 0

        if (!hasEdges && !hasStates && !hasClasses) {
            regionStore.setHighlightDataFast(sourceRid, highlightNodes, highlightEdges)
            return
        }

        // -------- 1. source region 的序列范围 --------

        const sourceSeqIds =
            sourceRid === "global"
                ? null
                : sourceRegion.sequenceIds

        // -------- 2. index lookup --------

        let candidateSeqIds = null

        if (hasEdges){

            for (const edge of edges){

                const s = cache.edgeToSeqIds.get(edge)
                if (!s) continue

                if (!candidateSeqIds)
                    candidateSeqIds = new Set(s)
                else
                    for (const id of s) candidateSeqIds.add(id)
            }

        }
        else if (hasClasses){

            for (const cls of classes){

                const s = cache.classToSeqIds.get(String(cls))
                if (!s) continue

                if (!candidateSeqIds)
                    candidateSeqIds = new Set(s)
                else
                    for (const id of s) candidateSeqIds.add(id)
            }

        }
        else if (hasStates){

            for (const state of states){

                const key = normalizeStateKey(state)
                const s = cache.stateToSeqIds.get(key)

                if (!s) continue

                if (!candidateSeqIds)
                    candidateSeqIds = new Set(s)
                else
                    for (const id of s) candidateSeqIds.add(id)
            }

        }

        if (!candidateSeqIds) return

        // -------- 3. 与 source region 求交 --------

        const matchedSeqIds = []
        const sourceSet = sourceSeqIds ? new Set(sourceSeqIds) : null

        for (const id of candidateSeqIds){
            if (!sourceSet || sourceSet.has(id)){
                matchedSeqIds.push(id)
            }
        }

        // -------- 4. 构建结果 --------

        for (const sid of matchedSeqIds){
            const feat = cache.seqHighlights.get(sid)

            if (!feat) continue

            for (const n of feat.nodes) highlightNodes.add(n)
            for (const e of feat.edges) highlightEdges.add(e)
        }

        regionStore.setHighlightDataFast(
            sourceRid,
            highlightNodes,
            highlightEdges
        )

        preview.value = {
            // targetRid 不在刷选阶段决定；由点击哪个 region 的 Apply 按钮来决定
            targetRid: null,
            sourceRid,
            brushId: b.id,
            raw: null,
            tok: null,
            seqIds: matchedSeqIds,
            count: matchedSeqIds.length,
            updatedAt: Date.now()
        }

        updateSourceInfoForBrush(b, sourceRid)
    }

    // ✅ 新增：把“当前 activeBrush”应用到“当前 activePanelRegionId”，优先走后端筛选
    async function commitActiveBrushToRegion() {
        ensureSequenceIndex()

        const b = activeBrush.value
        if (!b) return

        const sourceRid = activePanelRegionId.value || "root"
        const sourceRegion = regionStore.regions[sourceRid]
        if (!sourceRegion) return

        const edges = b.edges || []
        const states = b.states
        const classes = b.classes

        const hasEdges = edges.length > 0
        const hasStates = states && states.size > 0
        const hasClasses = classes && classes.size > 0

        if (!hasEdges && !hasStates && !hasClasses) {
            regionStore.setHighlightDataFast(sourceRid, new Set(), new Set())
            return
        }

        const sourceSeqIds =
            sourceRid === "global"
                ? null
                : sourceRegion.sequenceIds

        try {
            const res = await fetch("http://localhost:8000/api/filter_sequences", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    edges: edges,
                    classes: Array.from(classes || []),
                    states: Array.from(states || []),
                    source_seq_ids: sourceSeqIds
                })
            })

            if (!res.ok) throw new Error("filter api failed")
            const data = await res.json()

            const matchedSeqIds = data.matched_seq_ids || []

            regionStore.setHighlightDataFast(
                sourceRid,
                new Set(data.highlight_nodes || []),
                new Set(data.highlight_edges || [])
            )

            preview.value = {
                targetRid: null,
                sourceRid,
                brushId: b.id,
                raw: null,
                tok: null,
                seqIds: matchedSeqIds,
                count: data.count ?? matchedSeqIds.length,
                updatedAt: Date.now()
            }

            updateSourceInfoForBrush(b, sourceRid)
            return
        } catch (e) {
            // 后端不可用时自动回退本地逻辑
            commitActiveBrushToRegionLocal()
        }
    }

    function toggleEdge(id, edgeKey) {
        const b = brushes.value[id]
        if (!b) return

        const i = b.edges.indexOf(edgeKey)
        if (i === -1) b.edges.push(edgeKey)
        else b.edges.splice(i,1)

        commitActiveBrushToRegion()
    }

    // ✅ 新增：在“当前激活 brush”上切换 state
    function toggleState(stateKey) {
        const b = activeBrush.value
        if (!b) return

        if (b.states.has(stateKey)) {
            b.states.delete(stateKey)
        } else {
            b.states.add(stateKey)
        }

        // syncClassesFromStates(b)
        commitActiveBrushToRegion()   // ⭐ 必须加
    }

    function toggleClass(cls) {
        const b = activeBrush.value
        if (!b) return

        // const payloadStore = usePayloadStore()
        // const states = payloadStore.payload?.glyph?.[cls]?.unique_states || []
        //
        // // 判断当前是不是“全选”
        // const allSelected =
        //     states.length > 0 &&
        //     states.every(st => b.states.has(payloadStore.stateKey(st)))
        //
        // // ⚠️ 关键点：直接操作 b.states，不走 toggleState
        // states.forEach(st => {
        //     const key = payloadStore.stateKey(st)
        //     if (allSelected) {
        //         b.states.delete(key)
        //     } else {
        //         b.states.add(key)
        //     }
        // })
        //
        // // ✅ 只在最后同步一次
        // syncClassesFromStates(b)


        // 现在：仅在 classes 集合上做 toggle，不再自动联动 states
        if (b.classes.has(cls)) {
            b.classes.delete(cls)
        } else {
            b.classes.add(cls)
        }

        commitActiveBrushToRegion()
    }


    function applyPreviewToSelectedRegion(targetRegionId) {
        const p = preview.value
        if (!p) return

        const regionStore = useRegionStore()
        const rid = targetRegionId || regionStore.activeRegionId
        if (!rid) return

        const fullRaw = payloadStore.payload?.raw_sequences || []
        const fullTok = payloadStore.payload?.first_order_sequences || []
        const ids = p.seqIds || []
        const raw = ids.map(sid => fullRaw[sid]).filter(Boolean)
        const tok = ids.map(sid => fullTok[sid]).filter(Boolean)

        if (!raw.length || !tok.length) return
        regionStore.setBaseSequencesFast(rid, raw, tok, ids)

        const sourceRegion = regionStore.regions[p.sourceRid]
        const sourceInfoValue =
            p.sourceRid === "global" ? "global" : (sourceRegion?.brushId ?? null)

        regionStore.setSourceInfo(rid, p.sourceRid, sourceInfoValue)
    }

    function applyPreviewToRegion(targetRid) {

        const p = preview.value
        if (!p) return

        const regionStore = useRegionStore()
        const fullRaw = payloadStore.payload?.raw_sequences || []
        const fullTok = payloadStore.payload?.first_order_sequences || []
        const ids = p.seqIds || []
        const raw = ids.map(sid => fullRaw[sid]).filter(Boolean)
        const tok = ids.map(sid => fullTok[sid]).filter(Boolean)
        if (!raw.length || !tok.length) return

        regionStore.setBaseSequencesFast(
            targetRid,
            raw,
            tok,
            ids
        )

        const sourceRegion = regionStore.regions[p.sourceRid]

        let sourceInfoValue;

        if (p.sourceRid === "global") {
            sourceInfoValue = "global"
        } else {
            sourceInfoValue = sourceRegion?.brushId ?? null
        }

        regionStore.setSourceInfo(
            targetRid,
            p.sourceRid,
            sourceInfoValue
        )
    }

    return {
        brushes,
        activeBrushId,
        activeBrush,

        activePanelRegionId,
        activePanelType,
        setActivePanelRegion,
        activeRegionForBrush,

        createBrush,
        removeBrush,
        clearBrushEdges,
        setActiveBrush,
        toggleEdge,
        toggleState,
        toggleClass,
        commitActiveBrushToRegion,

        // 点击了之后才画图
        preview,
        applyPreviewToSelectedRegion,
        applyPreviewToRegion,
    }
})

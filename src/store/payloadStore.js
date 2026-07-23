import { defineStore } from "pinia"
import { ref, computed } from "vue"
import * as d3 from "d3"
import { useBrushStore } from "@/store/brushStore"

export const usePayloadStore = defineStore("payload", () => {

    /* ======================
     * state
     * ====================== */

    /** 当前视图用的 payload（可能被切分类等操作更新） */
    const payload = ref(null)

    /** 原始 payload，不被切分类覆盖；用于“恢复为原始” */
    const originalPayload = ref(null)

    const selectedStates = ref(new Set())
    const selectedClasses = ref(new Set())
    const selectedFirstOrderState = ref(null)
    const selectedHighOrderClass = ref(null)
    const selectedFirstOrderRegionId = ref(null)
    const selectedHighOrderRegionId = ref(null)
    const hoveredAppendEvent = ref(null)
    const focusedAppendEvent = ref(null)
    const hoveredHighOrderClasses = ref([])

    const mode = ref("contiguous")

    // window control
    const prevSteps = ref(null)
    const nextSteps = ref(null)
    const windowMode = ref("split")

    const colorScale = ref(null)

    // 全局图（GraphGlyph）节点布局坐标：用于让 ForceGraph 子图复用同一套节点相对布局
    // key: String(node.id) -> { x, y }
    const globalGraphNodePositions = ref(null)
    const globalGraphLayoutBounds = ref(null)
    const highOrderLayoutMode = ref("force")

    /* ======================
     * helpers
     * ====================== */

    function normalize(x) {
        return String(x).trim()
    }

    function cleanStateToken(x) {
        return String(x)
            .replace(/[()']/g, "")
            .trim()
    }

    function stateKey(arr) {
        return arr.map(normalize).join("→")
    }

    function stateKeyClean(arr) {
        return arr.map(cleanStateToken).join("→")
    }

    /* ======================
     * actions
     * ====================== */

    function toggleState(key, cls) {

        const s = new Set(selectedStates.value)

        if (s.has(key)) s.delete(key)
        else s.add(key)

        selectedStates.value = s

        updateClassSelection(cls)
    }

    function clearStates() {
        selectedStates.value = new Set()
    }

    function setFirstOrderState(state, regionId = "global") {
        selectedFirstOrderState.value = state == null ? null : String(state)
        selectedFirstOrderRegionId.value = selectedFirstOrderState.value ? String(regionId || "global") : null
        if (selectedFirstOrderState.value) {
            selectedHighOrderClass.value = null
            selectedHighOrderRegionId.value = null
        }
    }

    function toggleFirstOrderState(state, regionId = "global") {
        const next = state == null ? null : String(state)
        const nextRegionId = String(regionId || "global")
        const isSame =
            selectedFirstOrderState.value === next &&
            selectedFirstOrderRegionId.value === nextRegionId
        selectedFirstOrderState.value = isSame ? null : next
        selectedFirstOrderRegionId.value = selectedFirstOrderState.value ? nextRegionId : null
        if (selectedFirstOrderState.value) {
            selectedHighOrderClass.value = null
            selectedHighOrderRegionId.value = null
        }
    }

    function setHighOrderClass(cls, regionId = "global") {
        selectedHighOrderClass.value = cls == null ? null : String(cls)
        selectedHighOrderRegionId.value = selectedHighOrderClass.value ? String(regionId || "global") : null
        if (selectedHighOrderClass.value) {
            selectedFirstOrderState.value = null
            selectedFirstOrderRegionId.value = null
        }
    }

    function toggleHighOrderClass(cls, regionId = "global") {
        const next = cls == null ? null : String(cls)
        const nextRegionId = String(regionId || "global")
        const isSame =
            selectedHighOrderClass.value === next &&
            selectedHighOrderRegionId.value === nextRegionId
        selectedHighOrderClass.value = isSame ? null : next
        selectedHighOrderRegionId.value = selectedHighOrderClass.value ? nextRegionId : null
        if (selectedHighOrderClass.value) {
            selectedFirstOrderState.value = null
            selectedFirstOrderRegionId.value = null
        }
    }

    function clearSelectionForRegion(regionId) {
        const rid = String(regionId || "global")
        if (selectedFirstOrderRegionId.value === rid) {
            selectedFirstOrderState.value = null
            selectedFirstOrderRegionId.value = null
        }
        if (selectedHighOrderRegionId.value === rid) {
            selectedHighOrderClass.value = null
            selectedHighOrderRegionId.value = null
        }
    }

    function setHoveredAppendEvent(eventName) {
        hoveredAppendEvent.value = eventName == null ? null : String(eventName)
    }

    function setFocusedAppendEvent(eventName) {
        focusedAppendEvent.value = eventName == null ? null : String(eventName)
    }

    function setHoveredHighOrderClasses(classIds) {
        hoveredHighOrderClasses.value = Array.isArray(classIds)
            ? classIds.filter(v => v != null).map(v => String(v))
            : []
    }

    function setStates(keys) {
        const s = new Set(selectedStates.value)
        keys.forEach(k => s.add(k))
        selectedStates.value = s
    }

    /**
     * 设置 payload
     * @param {object} data - 后端返回或切分类后构造的 payload
     * @param {object} [opts]
     * @param {boolean} [opts.setAsOriginal=true] - 是否同时设为“原始数据”（上传/rewrite 时 true，切分类结果时 false）
     */
    function setPayload(data, opts = {}) {
        const { setAsOriginal = true } = opts
        payload.value = data
        if (setAsOriginal && data != null) {
            originalPayload.value = deepCopyPayload(data)
        }
    }

    /** 深拷贝 payload（用于保留原始引用不被后续修改影响） */
    function deepCopyPayload(p) {
        if (p == null) return null
        return JSON.parse(JSON.stringify(p))
    }

    /** 恢复为原始 payload（不覆盖 originalPayload，仅把当前视图还原） */
    function resetToOriginal() {
        if (originalPayload.value == null) return
        payload.value = deepCopyPayload(originalPayload.value)
    }

    function clearPayload() {

        payload.value = null
        originalPayload.value = null
        selectedStates.value = new Set()
        selectedFirstOrderState.value = null
        selectedFirstOrderRegionId.value = null
        selectedHighOrderClass.value = null
        selectedHighOrderRegionId.value = null

        prevSteps.value = null
        nextSteps.value = null
        windowMode.value = "split"
    }

    function toggleClass(cls) {

        cls = String(cls)

        const c = new Set(selectedClasses.value)

        if (c.has(cls)) c.delete(cls)
        else c.add(cls)

        selectedClasses.value = c

        const states = payload.value?.glyph?.[cls]?.unique_states || []

        const s = new Set(selectedStates.value)

        states.forEach(st => {

            const key = stateKey(st)

            if (c.has(cls)) s.add(key)
            else s.delete(key)
        })

        selectedStates.value = s
    }

    function updateClassSelection(cls) {

        if (!cls || !payload.value?.glyph?.[cls]) return

        const states = payload.value.glyph[cls].unique_states

        const allSelected =
            states.length > 0 &&
            states.every(st => selectedStates.value.has(stateKey(st)))

        const c = new Set(selectedClasses.value)

        if (allSelected) c.add(String(cls))
        else c.delete(String(cls))

        selectedClasses.value = c
    }

    function buildGlobalColorScale(tokens) {
        const palette = [
            ...d3.schemeTableau10,
            ...(d3.schemeSet3 || []),
            ...(d3.schemePaired || [])
        ]

        colorScale.value = d3.scaleOrdinal()
            .domain(tokens)
            .range(tokens.map((_, i) => palette[i % palette.length]))

    }

    function setGlobalGraphNodePositions(posById, bounds = null) {
        globalGraphNodePositions.value = posById ? { ...posById } : {}
        globalGraphLayoutBounds.value = bounds
    }

    function updateGlobalGraphNodePosition(id, x, y) {
        const key = String(id)
        const prev = globalGraphNodePositions.value || {}
        globalGraphNodePositions.value = {
            ...prev,
            [key]: { x, y }
        }
    }

    function setHighOrderLayoutMode(mode) {
        highOrderLayoutMode.value = (mode === "layered" || mode === "sequence") ? "layered" : "force"
    }

    /* ======================
     * filtered payload
     * ====================== */

    const filteredPayload = computed(function filteredPayloadComputed() {

        const p = payload.value
        if (!p) return null

        const brushStore = useBrushStore()
        const preview = brushStore.preview?.value

        if (!preview || !preview.seqIds || preview.seqIds.length === 0) {
            return null
        }

        const newRawSeqs = []
        const newTokSeqs = []
        const newSeqIds = []

        const raw = p.raw_sequences || []
        const tok = p.first_order_sequences || []
        const ids = p.sequence_ids || []

        for (const sid of preview.seqIds) {

            if (raw[sid]) newRawSeqs.push(raw[sid])
            if (tok[sid]) newTokSeqs.push(tok[sid])
            if (ids[sid]) newSeqIds.push(ids[sid])
        }

        return {
            ...p,
            raw_sequences: newRawSeqs,
            first_order_sequences: newTokSeqs,
            sequence_ids: newSeqIds
        }
    })

    /* ======================
     * expose
     * ====================== */

    return {

        payload,

        selectedStates,
        selectedClasses,
        selectedFirstOrderState,
        selectedHighOrderClass,
        selectedFirstOrderRegionId,
        selectedHighOrderRegionId,
        hoveredAppendEvent,
        focusedAppendEvent,
        hoveredHighOrderClasses,

        mode,

        prevSteps,
        nextSteps,
        windowMode,

        stateKey,
        toggleState,
        clearStates,
        setStates,
        setFirstOrderState,
        toggleFirstOrderState,
        setHighOrderClass,
        toggleHighOrderClass,
        clearSelectionForRegion,
        setHoveredAppendEvent,
        setFocusedAppendEvent,
        setHoveredHighOrderClasses,

        toggleClass,

        setPayload,
        clearPayload,
        resetToOriginal,
        originalPayload,

        filteredPayload,

        colorScale,
        buildGlobalColorScale,

        globalGraphNodePositions,
        globalGraphLayoutBounds,
        highOrderLayoutMode,
        setGlobalGraphNodePositions,
        updateGlobalGraphNodePosition,
        setHighOrderLayoutMode,
    }

})

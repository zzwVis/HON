import * as d3 from "d3"
import dagre from "dagre"

// ===============================
// HoNVis-style normalized entropy
// ===============================
export function honvisEntropyFromLinks(links) {
    if (!links || links.length === 0) return 0

    // 使用 raw transition counts / probs
    const values = links.map(l => l.raw_value).filter(v => v > 0)
    const sum = d3.sum(values)

    if (sum <= 0) return 0

    let H = 0
    for (const v of values) {
        const p = v / sum
        H -= p * Math.log(p)
    }

    return H
}

export function computeLayerMap(eventSeqs) {
    const sum = new Map(), cnt = new Map()
    for (const seq of eventSeqs || []) {
        seq.forEach((c, i) => {
            sum.set(c, (sum.get(c) || 0) + i)
            cnt.set(c, (cnt.get(c) || 0) + 1)
        })
    }
    const layer = new Map()
    for (const [c, s] of sum.entries()) {
        layer.set(String(c), s / cnt.get(c))
    }
    return layer
}

export function applyLayeredLayout(nodes, links, options = {}) {
    if (!Array.isArray(nodes) || nodes.length === 0) return

    const nodeW = options.nodeW ?? 72
    const nodeH = options.nodeH ?? 28
    const ranksep = options.ranksep ?? 18
    const nodesep = options.nodesep ?? Math.max(14, nodeH * 0.8)

    const g = new dagre.graphlib.Graph({
        directed: true,
        multigraph: true,
    })
    g.setGraph({
        rankdir: "LR",
        ranksep,
        nodesep,
        marginx: 0,
        marginy: 0,
        acyclicer: "greedy",
        ranker: "network-simplex",
    })
    g.setDefaultEdgeLabel(() => ({}))

    nodes.forEach(node => {
        g.setNode(String(node.id), {
            width: nodeW,
            height: nodeH,
        })
    })

    let edgeIndex = 0
    ;(links || []).forEach(link => {
        const source = typeof link.source === "object" ? link.source.id : link.source
        const target = typeof link.target === "object" ? link.target.id : link.target
        const sid = String(source)
        const tid = String(target)
        if (!sid || !tid || sid === tid) return
        if (!g.hasNode(sid) || !g.hasNode(tid)) return
        g.setEdge(sid, tid, {
            weight: Math.max(1, Number(link.value ?? 1)),
        }, `e${edgeIndex++}`)
    })

    dagre.layout(g)

    nodes.forEach(node => {
        const p = g.node(String(node.id))
        if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) {
            node.x = p.x
            node.y = p.y
        }
    })
}

export function taperedLinkPath(d, w0 = 8, w1 = 1) {
    const x1 = d.source.x
    const y1 = d.source.y
    const x2 = d.target.x
    const y2 = d.target.y

    const dx = x2 - x1
    const dy = y2 - y1
    const len = Math.sqrt(dx*dx + dy*dy)
    if (len === 0) return ""

    const ux = dx / len
    const uy = dy / len
    const nx = -uy
    const ny = ux

    const a1x = x1 + nx * w0
    const a1y = y1 + ny * w0
    const b1x = x1 - nx * w0
    const b1y = y1 - ny * w0

    const a2x = x2 + nx * w1
    const a2y = y2 + ny * w1
    const b2x = x2 - nx * w1
    const b2y = y2 - ny * w1

    return `
    M ${a1x},${a1y}
    L ${a2x},${a2y}
    L ${b2x},${b2y}
    L ${b1x},${b1y}
    Z
  `
}

export function applyBarycentricY(nodes, links, strength = 0.15) {
    const neighborYs = new Map()

    links.forEach(l => {
        const s = l.source
        const t = l.target

        if (!neighborYs.has(s.id)) neighborYs.set(s.id, [])
        if (!neighborYs.has(t.id)) neighborYs.set(t.id, [])

        neighborYs.get(s.id).push(t.y)
        neighborYs.get(t.id).push(s.y)
    })

    nodes.forEach(n => {
        const ys = neighborYs.get(n.id)
        if (ys && ys.length > 0) {
            const avg = d3.mean(ys)
            n.y += (avg - n.y) * strength
        }
    })
}

export function curvedTaperedLinkPath(d, maxW = 10, minW = 1) {

    const x1 = d.source.x
    const y1 = d.source.y
    const x2 = d.target.x
    const y2 = d.target.y

    // ⭐ 中心（用两点中点近似全局中心）
    const cx = (x1 + x2) / 2
    const cy = (y1 + y2) / 2

    const dx = x2 - x1
    const dy = y2 - y1

    const dist = Math.sqrt(dx*dx + dy*dy) || 1


    // =========================
    // ⭐ 用中心坐标算角度
    // =========================

    const a1 = Math.atan2(y1 - cy, x1 - cx)
    const a2 = Math.atan2(y2 - cy, x2 - cx)

    let da = Math.abs(a2 - a1)
    if (da > Math.PI) da = 2*Math.PI - da


    // =========================
    // ⭐ 曲率控制（更稳定）
    // =========================

    let curvature = 0.25 + da * 0.5

    // 限制范围
    curvature = Math.max(0.2, Math.min(curvature, 0.9))


    // =========================
    // ⭐ 法线方向
    // =========================

    const nx = -dy / dist
    const ny = dx / dist


    // ⭐ 控制弯曲幅度
    const bend = curvature * dist * 0.5

    const cx1 = (x1 + x2) / 2 + nx * bend
    const cy1 = (y1 + y2) / 2 + ny * bend


    // =========================
    // taper
    // =========================

    const ux = -dy / dist
    const uy = dx / dist

    const w1 = maxW
    const w2 = minW

    const p1 = `${x1 + ux*w1},${y1 + uy*w1}`
    const p2 = `${cx1 + ux*((w1+w2)/2)},${cy1 + uy*((w1+w2)/2)}`
    const p3 = `${x2 + ux*w2},${y2 + uy*w2}`

    const p4 = `${x2 - ux*w2},${y2 - uy*w2}`
    const p5 = `${cx1 - ux*((w1+w2)/2)},${cy1 - uy*((w1+w2)/2)}`
    const p6 = `${x1 - ux*w1},${y1 - uy*w1}`

    return `
      M${p1}
      Q${p2} ${p3}
      L${p4}
      Q${p5} ${p6}
      Z
    `
}

export function selfLoopTaperedPath(d, NODE_W, NODE_H, loopHeightParam = 0.8, halfWidthParam = 0.25){

    const x = d.source.x
    const y = d.source.y

    const horizontal = NODE_W >= NODE_H

    if (horizontal) {
        // 画在上边

        const margin = 0                    // 离矩形边缘的间距
        const loopHeight = NODE_H * loopHeightParam     // ★ 原来 1.4 → 改成 0.8
        const halfWidth = NODE_W * halfWidthParam     // 环的横向展开

        const y0 = y - NODE_H / 2 - margin
        const sx = x - halfWidth
        const ex = x + halfWidth

        return `
      M ${sx},${y0}
      C ${sx},${y0 - loopHeight}
        ${ex},${y0 - loopHeight}
        ${ex},${y0}
    `
    }
    else {
        // 画在右边

        const margin = 6
        const loopWidth = NODE_W * 0.8      // ★ 原来 1.4 → 改成 0.8
        const halfHeight = NODE_H * 0.25

        const x0 = x + NODE_W / 2 + margin
        const sy = y - halfHeight
        const ey = y + halfHeight

        return `
      M ${x0},${sy}
      C ${x0 + loopWidth},${sy}
        ${x0 + loopWidth},${ey}
        ${x0},${ey}
    `
    }
}

export function sliceSequencesByStatePos(
    rawSeqs,                 // filtered raw_sequences
    filteredSeqId2Index,     // ⭐ 新增：sid -> filtered index
    state2posIndex,
    selectedStates,
    prevN,
    nextN,
    mode
) {

    const states = Array.isArray(selectedStates)
        ? selectedStates
        : Array.from(selectedStates)

    const results = []

    states.forEach(st => {
        const key = canonicalJsonKey(stateKey(st))

        const posMap = state2posIndex.get(key)

        if (!posMap) return

        // posMap: { seq_id : [t1, t2, ...] }
        Object.entries(posMap).forEach(([sid, timesteps]) => {

            // ✅ 关键修改 1：通过映射找 filtered index
            console.log("sid",sid)
            console.log("filteredSeqId2Index",filteredSeqId2Index)
            const filteredIdx = filteredSeqId2Index.get(String(sid))
            console.log("filteredIdx",filteredIdx)
            if (filteredIdx == null) return

            const seq = rawSeqs[filteredIdx]

            if (!seq) return

            const windows = timesteps.map(t => ({
                start: Math.max(0, t - prevN),
                end:   Math.min(seq.length, t + nextN + 1)
            }))

            if (mode === "split") {

                windows.forEach(w => {
                    results.push(seq.slice(w.start, w.end))
                })

            } else { // union

                const start = Math.min(...windows.map(w => w.start))
                const end   = Math.max(...windows.map(w => w.end))
                results.push(seq.slice(start, end))

            }
        })
    })

    return results
}

export function canonicalJsonKey(k) {
    try { return JSON.stringify(JSON.parse(k)) }
    catch { return String(k).trim() }
}

export function stateKey(st) {
    if (Array.isArray(st)) return JSON.stringify(st) // canonical
    const s = String(st).trim()
    if (s.startsWith("[")) return canonicalJsonKey(s) // 可能已经是 json 字符串
    if (s.includes("→")) return JSON.stringify(s.split("→"))
    return JSON.stringify([s])
}

export function computeMaxWindowRange(
    rawSeqs,
    filteredSeqId2Index,
    state2posIndex,
    selectedStates
) {

    const states = Array.isArray(selectedStates)
        ? selectedStates
        : Array.from(selectedStates)

    let maxPrev = 0
    let maxNext = 0

    states.forEach(st => {

        const key = stateKey(st)
        const posMap = state2posIndex.get(key)
        if (!posMap) return

        Object.entries(posMap).forEach(([sid, timesteps]) => {

            const idx = filteredSeqId2Index.get(String(sid))
            if (idx == null) return

            const seq = rawSeqs[idx]
            if (!seq) return

            timesteps.forEach(t => {

                maxPrev = Math.max(maxPrev, t)
                maxNext = Math.max(maxNext, seq.length - 1 - t)

            })
        })
    })

    return { maxPrev, maxNext }
}

// 一阶->高阶
export function firstOrderToHighOrder(seq, maxOrder) {
    const res = []
    for (let i = 0; i < seq.length; i++) {
        const start = Math.max(0, i - maxOrder + 1)
        res.push(seq.slice(start, i + 1))
    }
    return res
}

// "A→B→C" -> ["A","B","C"]
// export function parseStateKeyToTokens(key) {
//     return String(key)
//         .split("→")
//         .map(s => s.trim())
//         .filter(Boolean)
// }

export function parseStateKeyToTokens(key) {
    return String(key)
        .split("→")
        .map(s =>
            s
                .replace(/[()']/g, "")   // ⭐ 去括号去引号
                .trim()
        )
        .filter(Boolean)
}


// seq: ["A","B","C","D"]
// pattern: ["B","C"]
// return: [[1,2]]
export function findSubseqPositions(seq, pattern) {
    const res = []

    if (pattern.length === 0) return res

    for (let i = 0; i <= seq.length - pattern.length; i++) {
        let ok = true
        for (let j = 0; j < pattern.length; j++) {
            if (seq[i + j] !== pattern[j]) {
                ok = false
                break
            }
        }
        if (ok) {
            res.push([i, i + pattern.length - 1])
        }
    }

    return res
}

// firstOrderSeqs : Array< Array<string> >
// selectedStates : Set<string>
// return { maxPrev, maxNext }
export function computeMaxWindowRangeFirstOrder(
    firstOrderSeqs,
    selectedStates
) {

    let maxPrev = 0
    let maxNext = 0

    const patterns = Array.from(selectedStates)
        .map(k => parseStateKeyToTokens(k))

    firstOrderSeqs.forEach(seq => {

        patterns.forEach(pat => {

            const hits = findSubseqPositions(seq, pat)

            hits.forEach(([s, e]) => {
                maxPrev = Math.max(maxPrev, s)
                maxNext = Math.max(maxNext, seq.length - 1 - e)
            })

        })

    })

    return { maxPrev, maxNext }
}

// mode: "split" | "union"
export function sliceSequencesFirstOrder(
    firstOrderSeqs,
    selectedStates,
    prevSteps,
    nextSteps,
    mode = "split"
) {

    const patterns = Array.from(selectedStates)
        .map(k => parseStateKeyToTokens(k))

    const results = []

    console.log("patterns", patterns)

    firstOrderSeqs.forEach(seq => {
        console.log("seq", seq)

        let windows = []

        patterns.forEach(pat => {
            const hits = findSubseqPositions(seq, pat)

            hits.forEach(([s, e]) => {

                const start = Math.max(0, s - prevSteps)
                const end   = Math.min(seq.length - 1, e + nextSteps)

                windows.push([start, end])
            })
        })

        if (windows.length === 0) return

        if (mode === "union") {
            const start = Math.min(...windows.map(w => w[0]))
            const end   = Math.max(...windows.map(w => w[1]))
            results.push(seq.slice(start, end + 1))
        } else {
            // split
            windows.forEach(([s, e]) => {
                results.push(seq.slice(s, e + 1))
            })
        }

    })

    return results
}

// 一阶到高阶的映射
export function buildHighOrderStatesFromFirstOrder(seq, maxOrder) {
    const res = []
    for (let i = 0; i < seq.length; i++) {
        const start = Math.max(0, i - maxOrder + 1)
        res.push(seq.slice(start, i + 1))
    }
    return res
}

// 状态到类的映射
export function buildStateKeyToClassMap(glyph, stateKeyClean) {
    const m = new Map()
    Object.entries(glyph || {}).forEach(([cls, g]) => {
        ;(g.unique_states || []).forEach(st => {
            const k = stateKeyClean(st)   // st 可能带括号/引号，stateKeyClean 内部要 clean
            m.set(k, Number(cls))
        })
    })
    return m
}

// stTokens: ["A","B","C"] 这种干净 token
export function stateTokensToClass(stTokens, st2clsMap, stateKeyClean) {
    // 逐步缩短：ABC -> BC -> C
    for (let cut = 0; cut < stTokens.length; cut++) {
        const sub = stTokens.slice(cut)
        const k = stateKeyClean(sub)
        if (st2clsMap.has(k)) return st2clsMap.get(k)
    }
    return null
}


// entropy function
export function entropyFromLinks(ls) {
    if (!ls || ls.length === 0) return 0

    const sum = d3.sum(ls, d => d.value)
    if (sum === 0) return 0

    let H = 0
    ls.forEach(d => {
        const p = d.value / sum
        if (p > 0) H -= p * Math.log(p)
    })
    return H
}

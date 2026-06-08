import * as d3 from "d3"

/** 在容器 g 内绘制一个 glyph（扇形序列），使用给定的宽高与圆心半径 */
function drawOneGlyph(g, ginfo, tokens, color, boxW, boxH, rMax = 12) {
    const posDist = ginfo.position_distributions || []
    const maxOrder = ginfo.max_order || 1
    const padding = 2
    const gap = 2
    const availableW = boxW - 2 * padding
    const availableH = boxH - 2 * padding

    const validDists = posDist.filter(dist =>
        tokens.some(t => (dist?.[t] || 0) > 0)
    )
    const nSteps = validDists.length
    if (nSteps === 0) return

    const perStepW = availableW / maxOrder
    const r = Math.max(3, Math.min(rMax, (perStepW - gap) / 2, availableH / 2 - 2))
    const totalGlyphW = nSteps * (2 * r + gap) - gap
    const baseX = padding + (availableW - totalGlyphW) / 2
    const baseY = padding

    const arc = d3.arc().innerRadius(0).outerRadius(r)
    const pie = d3.pie().sort(null).value(e => e.value)
    validDists.forEach((dist, i) => {
        const entries = tokens
            .map(t => ({ token: t, value: dist[t] || 0 }))
            .filter(e => e.value > 0)
        if (entries.length === 0) return
        const cx = baseX + i * (2 * r + gap) + r
        const cy = baseY + availableH / 2
        const pg = g.append("g").attr("transform", `translate(${cx}, ${cy})`)
        pg.selectAll("path")
            .data(pie(entries))
            .enter()
            .append("path")
            .attr("d", arc)
            .attr("fill", p => color(p.data.token))
            .attr("stroke", "#fff")
            .attr("stroke-width", 0.8)
    })
}

export function drawGlyphForce(nodeSel, glyphData, tokens, color, NODE_W, NODE_H) {
    nodeSel.each(function(d) {
        d3.select(this).selectAll(".glyph").remove()
        const ginfo = glyphData[String(d.class)]

        if (!ginfo) return
        const g = d3.select(this)
            .append("g")
            .attr("class", "glyph")
            .attr("transform", `translate(${-NODE_W/2}, ${-NODE_H/2})`)
        drawOneGlyph(g, ginfo, tokens, color, NODE_W, NODE_H, 12)
    })
}
/**
 * Memory-split findings from an existing HONVis payload.
 * A first-order event is a "split" when it occurs in 2+ high-order
 * nodes with different next-step distributions. Read-only.
 */

export function normalizeSplitToken(x) {
  return String(x ?? "")
      .trim()
      .replace(/^['"]|['"]$/g, "")
      .replace(/[']/g, "")
}

export function splitTokenKey(x) {
  return normalizeSplitToken(x).toLowerCase()
}

function sameToken(a, b) {
  return splitTokenKey(a) === splitTokenKey(b)
}

function addCount(map, key, amount = 1) {
  map.set(key, (map.get(key) || 0) + amount)
}

function countTotal(counts) {
  let total = 0
  counts.forEach(value => {
    total += value
  })
  return total
}

function klDivergence(sourceCounts, baselineCounts) {
  if (countTotal(sourceCounts) <= 0 || countTotal(baselineCounts) <= 0) return 0

  const keys = new Set([...sourceCounts.keys(), ...baselineCounts.keys()])
  if (keys.size === 0) return 0

  const sourceTotal = countTotal(sourceCounts)
  const baselineTotal = countTotal(baselineCounts)
  const epsilon = 1e-6
  const smoothDenominator = 1 + epsilon * keys.size

  let value = 0
  keys.forEach(key => {
    const pv = ((sourceCounts.get(key) || 0) / sourceTotal + epsilon) / smoothDenominator
    const qv = ((baselineCounts.get(key) || 0) / baselineTotal + epsilon) / smoothDenominator
    value += pv * Math.log2(pv / qv)
  })

  if (Math.abs(value) < 1e-10) return 0
  return Math.max(0, value)
}

function topNext(counts) {
  let bestKey = null
  let bestValue = 0
  counts.forEach((value, key) => {
    if (value > bestValue) {
      bestKey = key
      bestValue = value
    }
  })
  const total = countTotal(counts)
  return {
    token: bestKey,
    count: bestValue,
    prob: total > 0 && bestKey != null ? bestValue / total : 0
  }
}

function displayToken(token, legend) {
  const raw = String(token ?? "").trim()
  const tokenList = Array.isArray(legend?.tokens) ? legend.tokens : []
  const hit = tokenList.find(t => sameToken(t, raw))
  return hit || raw
}

/**
 * @param {object|null} payload HONVis payload
 * @param {{ maxItems?: number }} [options]
 */
export function computeMemorySplits(payload, options = {}) {
  const maxItems = Number.isFinite(options.maxItems) ? options.maxItems : 12
  const firstSeqs = payload?.first_order_sequences || []
  const classSeqs = payload?.raw_sequences || []
  const legend = payload?.legend

  if (!payload || firstSeqs.length === 0 || classSeqs.length === 0) {
    return []
  }

  const byLastToken = new Map()

  function bucketFor(lastToken) {
    const key = splitTokenKey(lastToken)
    if (!byLastToken.has(key)) {
      byLastToken.set(key, {
        token: lastToken,
        tokenKey: key,
        occurrences: 0,
        classes: new Map()
      })
    }
    return byLastToken.get(key)
  }

  function classBucket(entry, classId) {
    if (!entry.classes.has(classId)) {
      entry.classes.set(classId, {
        classId,
        occurrences: 0,
        nextCounts: new Map()
      })
    }
    return entry.classes.get(classId)
  }

  firstSeqs.forEach((firstSeq, sid) => {
    const classSeq = classSeqs[sid]
    if (!Array.isArray(firstSeq) || !Array.isArray(classSeq)) return
    const n = Math.min(firstSeq.length, classSeq.length)
    for (let t = 0; t < n; t++) {
      const classId = String(classSeq[t])
      if (classId === "-1" || classId === "undefined" || classId === "null") continue
      const lastToken = firstSeq[t]
      if (lastToken == null || lastToken === "") continue
      const entry = bucketFor(lastToken)
      entry.occurrences += 1
      const cls = classBucket(entry, classId)
      cls.occurrences += 1
      if (t + 1 < firstSeq.length) {
        addCount(cls.nextCounts, splitTokenKey(firstSeq[t + 1]))
      }
    }
  })

  const splits = []

  byLastToken.forEach(entry => {
    const classRows = Array.from(entry.classes.values())
        .filter(row => row.occurrences > 0)
        .sort((a, b) => b.occurrences - a.occurrences)

    if (classRows.length < 2) return

    let maxPairKl = 0
    let left = classRows[0]
    let right = classRows[1]
    for (let i = 0; i < classRows.length; i++) {
      for (let j = i + 1; j < classRows.length; j++) {
        const kl = Math.max(
            klDivergence(classRows[i].nextCounts, classRows[j].nextCounts),
            klDivergence(classRows[j].nextCounts, classRows[i].nextCounts)
        )
        if (kl > maxPairKl) {
          maxPairKl = kl
          left = classRows[i]
          right = classRows[j]
        }
      }
    }

    const contrast = [left, right].map(row => {
      const next = topNext(row.nextCounts)
      return {
        classId: row.classId,
        occurrences: row.occurrences,
        nextToken: next.token,
        nextLabel: next.token ? displayToken(next.token, legend) : "none",
        nextProb: next.prob
      }
    })

    splits.push({
      token: entry.token,
      tokenKey: entry.tokenKey,
      label: displayToken(entry.token, legend),
      occurrences: entry.occurrences,
      hoNodeCount: classRows.length,
      classIds: classRows.map(row => row.classId),
      maxPairKl,
      contrast
    })
  })

  splits.sort((a, b) =>
      b.maxPairKl - a.maxPairKl ||
      b.hoNodeCount - a.hoNodeCount ||
      b.occurrences - a.occurrences
  )

  return splits.slice(0, maxItems)
}

export function findMemorySplit(splits, token) {
  if (!token || !Array.isArray(splits)) return null
  const key = splitTokenKey(token)
  return splits.find(item => item.tokenKey === key) || null
}

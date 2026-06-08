// 唯一的边key
export function edgeKey(d) {
    return `${d.source.id} → ${d.target.id}`
}
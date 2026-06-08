let cache = null
let fullRaw = null
let fullTok = null

self.onmessage = function(e){

    const { type, payload } = e.data

    if(type === "init"){

        cache = payload.cache
        fullRaw = payload.fullRaw
        fullTok = payload.fullTok

        return
    }

    if(type === "filter"){

        const {
            edges,
            states,
            classes,
            sourceSeqIds
        } = payload

        const highlightNodes = new Set()
        const highlightEdges = new Set()

        const matchedRaw = []
        const matchedTok = []
        const matchedSeqIds = []

        let candidateSeqIds = null

        if(edges?.length){

            for(const edge of edges){

                const s = cache.edgeToSeqIds[edge]
                if(!s) continue

                if(!candidateSeqIds)
                    candidateSeqIds = new Set(s)
                else
                    s.forEach(id=>candidateSeqIds.add(id))
            }

        }
        else if(classes?.length){

            for(const cls of classes){

                const s = cache.classToSeqIds[cls]
                if(!s) continue

                if(!candidateSeqIds)
                    candidateSeqIds = new Set(s)
                else
                    s.forEach(id=>candidateSeqIds.add(id))
            }

        }
        else if(states?.length){

            for(const state of states){

                const s = cache.stateToSeqIds[state]
                if(!s) continue

                if(!candidateSeqIds)
                    candidateSeqIds = new Set(s)
                else
                    s.forEach(id=>candidateSeqIds.add(id))
            }

        }

        if(!candidateSeqIds){
            self.postMessage({
                highlightNodes:[],
                highlightEdges:[],
                matchedRaw:[],
                matchedTok:[],
                matchedSeqIds:[]
            })
            return
        }

        for(const sid of candidateSeqIds){

            if(sourceSeqIds && !sourceSeqIds.includes(sid)) continue

            matchedSeqIds.push(sid)

            const seq = fullRaw[sid]
            const tok = fullTok[sid]

            matchedRaw.push(seq)
            matchedTok.push(tok)

            const feat = cache.seqHighlights[sid]

            if(!feat) continue

            feat.nodes.forEach(n=>highlightNodes.add(n))
            feat.edges.forEach(e=>highlightEdges.add(e))
        }

        self.postMessage({
            highlightNodes:[...highlightNodes],
            highlightEdges:[...highlightEdges],
            matchedRaw,
            matchedTok,
            matchedSeqIds
        })
    }
}
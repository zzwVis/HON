from flask import Flask, jsonify, request
from flask_cors import CORS
from collections import Counter
import numpy as np
from collections import defaultdict
import json
import pandas as pd
import ast
import tempfile
import os
import torch
from network import PolicyNet
import torch.nn.functional as F

PLACEHOLDER = "占位符"
INPUT_XLSX = "data/semantic_agavue_2000.xlsx"
DEFAULT_K = 3

app = Flask(__name__)
CORS(app)   # 允许前端跨域访问

CKPT_PATH = "model/semantic_agavue_full_ckpt_seed3.pt"

ckpt = torch.load(CKPT_PATH, map_location="cpu", weights_only=False)

print("ckpt keys:", ckpt.keys())

cfg = ckpt["config"]

# ===== state_dim 必须来自 dims =====
state_dim = cfg["dims"][-1]

hidden_dim = 128
max_kl = cfg.get("max_kl", 50.0)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

policy_net = PolicyNet(
    state_dim=state_dim,
    hidden_dim=hidden_dim,
    max_kl=max_kl,
).to(device)

policy_net.load_state_dict(ckpt["policy_net"])

policy_net.eval()

# 当前前端正在使用的 payload（用于后端筛选接口）
CURRENT_PAYLOAD = None
CURRENT_DF = None
CURRENT_STATE_MAP_DF = None
FILTER_INDEX_CACHE = None
FILTER_INDEX_VERSION = 0

# -------------------------
# utils
# -------------------------
def parse_state(x):
    if isinstance(x, (tuple, list)):
        return tuple(x)
    if pd.isna(x):
        return tuple()

    if isinstance(x, str):
        try:
            v = ast.literal_eval(x)
            if isinstance(v, (tuple, list)):
                return tuple(v)
            else:
                return (str(v),)
        except Exception:
            # fallback：按逗号切
            return tuple(s.strip() for s in x.split(",") if s.strip())

    return (str(x),)

def normalize_state_key(k):
    return str(k).replace("(", "").replace(")", "").replace("'", "").strip()

def set_current_payload(payload):
    global CURRENT_PAYLOAD, FILTER_INDEX_CACHE, FILTER_INDEX_VERSION
    CURRENT_PAYLOAD = payload
    FILTER_INDEX_CACHE = None
    FILTER_INDEX_VERSION += 1

def set_current_df(df):
    global CURRENT_DF
    CURRENT_DF = df.copy() if isinstance(df, pd.DataFrame) else None

def set_current_state_map(map_df):
    global CURRENT_STATE_MAP_DF
    if isinstance(map_df, pd.DataFrame):
        CURRENT_STATE_MAP_DF = map_df.copy()
    else:
        CURRENT_STATE_MAP_DF = None

def build_filter_index(payload):
    raw_seqs = payload.get("raw_sequences", []) or []
    tok_seqs = payload.get("first_order_sequences", []) or []

    edge_to_seq_ids = defaultdict(set)
    state_to_seq_ids = defaultdict(set)
    class_to_seq_ids = defaultdict(set)
    seq_highlights = {}

    for sid, raw in enumerate(raw_seqs):
        tok = tok_seqs[sid] if sid < len(tok_seqs) else []
        nodes = []
        edges = []

        for i, cls in enumerate(raw):
            node_key = f"node{cls}"
            nodes.append(node_key)

            if i < len(raw) - 1:
                edge_key = f"node{raw[i]}→node{raw[i+1]}"
                edges.append(edge_key)
                edge_to_seq_ids[edge_key].add(sid)

        seq_highlights[sid] = {"nodes": nodes, "edges": edges}

        for cls in set(str(v) for v in raw):
            class_to_seq_ids[cls].add(sid)

        tokens = [normalize_state_key(x) for x in tok]
        for i in range(len(tokens)):
            acc = tokens[i]
            state_to_seq_ids[acc].add(sid)
            for j in range(i + 1, len(tokens)):
                acc += "→" + tokens[j]
                state_to_seq_ids[acc].add(sid)

    return {
        "edge_to_seq_ids": edge_to_seq_ids,
        "state_to_seq_ids": state_to_seq_ids,
        "class_to_seq_ids": class_to_seq_ids,
        "seq_highlights": seq_highlights,
        "version": FILTER_INDEX_VERSION,
    }

def get_filter_index():
    global FILTER_INDEX_CACHE
    if CURRENT_PAYLOAD is None:
        return None
    if FILTER_INDEX_CACHE is None:
        FILTER_INDEX_CACHE = build_filter_index(CURRENT_PAYLOAD)
    return FILTER_INDEX_CACHE

def normalize_logic(value):
    return "AND" if str(value).upper() == "AND" else "OR"

def combine_seq_sets(seq_sets, logic):
    seq_sets = [set(s) for s in seq_sets]
    if not seq_sets:
        return set()

    if normalize_logic(logic) == "AND":
        result = seq_sets[0]
        for s in seq_sets[1:]:
            result &= s
        return result

    result = set()
    for s in seq_sets:
        result |= s
    return result

def match_filter_group(values, logic, index_map):
    if not values:
        return None
    return combine_seq_sets((index_map.get(v, set()) for v in values), logic)

def rewrite_highorder(
    input_xlsx,
    state_cluster_csv,
    K=3
):

    df = pd.read_excel(input_xlsx, engine="openpyxl")

    df["id"] = df["id"].astype(int)
    df["position"] = df["position"].astype(int)
    df["event"] = df["event"].astype(str)

    df = df.sort_values(
        ["id", "position"]
    ).reset_index(drop=True)

    map_df = pd.read_csv(state_cluster_csv)

    map_df["state_tuple"] = map_df["state"].apply(parse_state)

    state2cluster = dict(
        zip(
            map_df["state_tuple"],
            map_df["cluster_id"]
        )
    )

    state_col = []
    cluster_col = []

    for sid, g in df.groupby("id", sort=False):

        events = g["event"].tolist()

        for t, ev in enumerate(events):

            start = max(0, t-K+1)

            st = tuple(events[start:t+1])

            state_col.append(st)
            cluster_col.append(state2cluster[st])

    df_out = df.copy()

    df_out["high_order_state"] = [
        str(s) for s in state_col
    ]

    df_out["semantic_class"] = cluster_col
    df_out["raw_event"] = df_out["event"].astype(str)
    df_out.attrs["max_order"] = K

    df_out.rename(
        columns={
            "id": "sequence_id",
            "position": "timestep",
            "event": "first_order_node",
        },
        inplace=True,
    )

    return df_out

def collapse_semantic_sequence(seq):
    """将 A-B-B-C 折叠为 A-B-C"""
    collapsed = []
    prev = None
    for c in seq:
        if prev is None or c != prev:
            collapsed.append(c)
            prev = c
    return collapsed

def clean_tok(tok):
    s = str(tok).strip()
    # 禁止 strip("()")：会把 "Attempt(Miss)" 误切成 "Attempt(Miss"，与 first_order_node / tokens 对不上，
    # 导致 position_distributions 里 Attempt(Miss) 等频率全为 0。
    # 仅当「整串被一对括号包住」时再剥外层，例如 "(Miss)" -> "Miss"
    if len(s) >= 2 and s[0] == "(" and s[-1] == ")":
        s = s[1:-1].strip()
    s = s.strip("'\"")
    s = s.replace(",", "")
    return s

def build_payload(df: pd.DataFrame):
    df["semantic_class"] = df["semantic_class"].astype(str)

    # ------- 1) 清洗 -------
    df = df.copy()
    # 记录每个高阶状态出现在哪些序列的哪些位置
    state2pos = defaultdict(lambda: defaultdict(list))

    df["high_order_state"] = df["high_order_state"].apply(parse_state)
    df["timestep"] = df["timestep"].astype(int)
    df["sequence_id"] = df["sequence_id"].astype(int)
    df["semantic_class"] = df["semantic_class"].astype(int)
    df["first_order_node"] = df["first_order_node"].astype(str)

    # 最大阶（glyph 对齐用）
    max_L = int(df.attrs.get("max_order") or df["high_order_state"].map(len).max() or 1)

    # =====================================================
    # === 2a) Sankey nodes + links (A0 B1 C2, 无环) ===
    # =====================================================

    node_map = {}        # (semantic_class, pos) -> node_index
    nodes = []
    link_counter = Counter()

    def get_node(c, pos):
        c = int(c)
        pos = int(pos)

        node_id = f"node{c}_pos{pos}"  # ⭐ 核心规则

        if node_id not in node_map:
            node_map[node_id] = True
            nodes.append({
                "id": node_id,  # Sankey 用（字符串）
                "class": c,  # semantic_class（数字）
                "pos": pos  # 序列位置
            })
        return node_id

    raw_sequences = []  # ⭐ 新增：存 semantic_class 序列
    sequence_ids = []  # ⭐ 新增 记录filtered后的序列在原始序列中的下标
    event_sequences = []
    first_order_sequences = [] # 存一阶节点序列

    # ------- 3) Sankey links（按 sequence 展开） -------
    for sid, g in df.sort_values(
            ["sequence_id", "timestep"]
    ).groupby("sequence_id"):

        g = g.reset_index(drop=True)

        for i, st in enumerate(g["high_order_state"]):
            if st is None:
                continue
            state2pos[tuple(st)][int(sid)].append(int(i))

        # ⭐ 新增 1：提取 semantic_class 序列
        seq = g["semantic_class"].astype(int).tolist()
        raw_sequences.append(seq)
        sequence_ids.append(int(sid))

        # ⭐ 新增：语义事件级（折叠）
        event_seq = collapse_semantic_sequence(seq)
        event_sequences.append(event_seq)

        # ⭐ 新增：first_order_node 一阶序列
        first_order_sequences.append(g["first_order_node"].astype(str).tolist())

        # 连续的只保留一次
        # for i in range(len(g) - 1):
        #     c1 = g.loc[i, "semantic_class"]
        #     c2 = g.loc[i + 1, "semantic_class"]
        #
        #     s = get_node(c1, i)
        #     t = get_node(c2, i + 1)
        #
        #     link_counter[(s, t)] += 1

        for i in range(len(event_seq) - 1):
            c1 = event_seq[i]
            c2 = event_seq[i + 1]

            s = get_node(c1, i)
            t = get_node(c2, i + 1)

            link_counter[(s, t)] += 1

    links = [
        {
            "source": str(s),
            "target": str(t),
            "value": int(v)
        }
        for (s, t), v in link_counter.items()
    ]

    # =====================================================
    # === 2b) Graph nodes + links (允许环/回流) ===
    # =====================================================

    graph_nodes = []
    graph_node_map = {}
    graph_link_counter = Counter()

    def get_graph_node(c):
        nid = f"node{int(c)}"
        if nid not in graph_node_map:
            graph_node_map[nid] = True
            graph_nodes.append({
                "id": nid,
                "class": int(c)
            })
        return nid

    for sid, g in df.sort_values(
            ["sequence_id", "timestep"]
    ).groupby("sequence_id"):

        seq = g["semantic_class"].astype(int).tolist()
        # Region rebuild marks warm-up states as -1. They are not visible high-order
        # clusters, so the context-map graph should connect adjacent visible clusters.
        event_seq = [int(c) for c in seq if int(c) >= 0]

        for c in event_seq:
            get_graph_node(c)

        for i in range(len(event_seq) - 1):
            c1 = event_seq[i]
            c2 = event_seq[i + 1]

            s = get_graph_node(c1)
            t = get_graph_node(c2)

            graph_link_counter[(s, t)] += 1

    graph_links = [
        {"source": s, "target": t, "value": int(v)}
        for (s, t), v in graph_link_counter.items()
    ]

    # =====================================================
    # === 3.5) raw_event -> first_order_node 映射
    # =====================================================
    RAW_COL = "raw_event"  # ✅ 改成你df里真实的raw事件列名

    raw2first = defaultdict(set)
    # 只要 (first_order_node, raw_event) 的唯一关系
    for first, raw in df[["first_order_node", RAW_COL]].dropna().itertuples(index=False):
        raw2first[str(first)].add(str(raw))

    # json-friendly
    raw2first = {k: sorted(list(v)) for k, v in raw2first.items()}

    # =====================================================
    # === 4) Glyph（类 → 多位置分布） ===
    # =====================================================

    tokens = sorted(
        set(df["first_order_node"].unique().tolist()) | {PLACEHOLDER}
    )

    glyph = {}

    for c, g in df.groupby("semantic_class"):

        pos_counter = [Counter() for _ in range(max_L)]
        full_order_pos_counter = [Counter() for _ in range(max_L)]

        # Previous type-composition implementation kept here for reference:
        # for st in set(tuple(x) for x in g["high_order_state"]):
        #     ...
        # It treated every unique high-order state equally. The graph edges,
        # however, are occurrence-level transitions, so glyphs now use the same
        # occurrence-weighted semantics: every row/timestep contributes once.
        for st in (tuple(x) for x in g["high_order_state"]):
            if len(st) == 0:
                continue
            start = max_L - len(st)
            for j, tok in enumerate(st):
                pos_counter[start + j][clean_tok(tok)] += 1
            if len(st) == max_L:
                for j, tok in enumerate(st):
                    full_order_pos_counter[j][clean_tok(tok)] += 1

        def counters_to_dist(counters):
            dist = []
            for cnt in counters:
                s = sum(cnt.values())
                if s == 0:
                    dist.append({t: 0.0 for t in tokens})
                else:
                    dist.append({t: cnt.get(t, 0) / s for t in tokens})
            return dist

        pos_dist = counters_to_dist(pos_counter)
        full_order_pos_dist = counters_to_dist(full_order_pos_counter)

        raw_states = [tuple(st) for st in g["high_order_state"].tolist()]

        state2seq = defaultdict(set)

        for st, sid in zip(
                g["high_order_state"],
                g["sequence_id"]
        ):
            state2seq[tuple(st)].add(int(sid))

        unique_state_tuples = list(state2seq.keys())
        unique_states = [list(st) for st in unique_state_tuples]
        full_order_states = [list(st) for st in unique_state_tuples if len(st) == max_L]
        warmup_states = [list(st) for st in unique_state_tuples if len(st) < max_L]

        full_order_state2seq = {
            json.dumps(list(st)): sorted(list(sids))
            for st, sids in state2seq.items()
            if len(st) == max_L
        }
        warmup_state2seq = {
            json.dumps(list(st)): sorted(list(sids))
            for st, sids in state2seq.items()
            if len(st) < max_L
        }

        supporting_seq_ids = {
            json.dumps(list(st)): sorted(list(sids))
            for st, sids in state2seq.items()
        }

        glyph[int(c)] = {
            "max_order": max_L,
            "composition_weighting": "occurrence",
            "position_distributions": pos_dist,
            "position_distributions_full_order": full_order_pos_dist,
            "raw_states": raw_states, # A-B-B-C
            "unique_states": unique_states,  # set (for detail view)
            "full_order_states": full_order_states,
            "warmup_states": warmup_states,
            "state2seq": supporting_seq_ids,  #记录每个高阶状态存在于哪些类中
            "full_order_state2seq": full_order_state2seq,
            "warmup_state2seq": warmup_state2seq
        }

    state2pos_json = {
        json.dumps(list(st)): {
            int(sid): [int(t) for t in ts]
            for sid, ts in seqmap.items()
        }
        for st, seqmap in state2pos.items()
    }

    # ------- 5) 最终 payload -------
    payload = {
        "sankey": {
            "nodes": nodes,   # 注意：现在是 A0 B1 C2 这种节点
            "links": links
        },
        "graph": {
            "nodes": graph_nodes,
            "links": graph_links
        },
        "glyph": glyph,
        "legend": {
            "tokens": tokens,
            "placeholder": PLACEHOLDER
        },
        "raw_sequences": raw_sequences, # semantic_class 序列（类序列）
        "sequence_ids": sequence_ids,
        "first_order_sequences": first_order_sequences,  # ⭐ 新增：first_order_node 序列（token 序列）
        "semantic_event_sequences": event_sequences,  # A-B-C
        "raw2first": raw2first,
        "state2pos": state2pos_json,
        "max_order": max_L
    }

    return payload

from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

def state_embedding_lookup_from_ckpt():
    lookup = {}
    state2idx = ckpt.get("state2idx", {}) or {}
    state_embeds = ckpt.get("state_embeds", None)
    if state_embeds is None:
        return lookup

    if isinstance(state_embeds, torch.Tensor):
        state_embeds = state_embeds.detach().cpu().numpy()

    for st, idx in state2idx.items():
        try:
            lookup[tuple(st)] = state_embeds[int(idx)].tolist()
        except Exception:
            continue

    return lookup

def short_state_repr(st, max_len=120):
    text = repr(st)
    return text if len(text) <= max_len else text[:max_len - 3] + "..."

def embedding_dim_of(emb):
    try:
        return int(len(emb))
    except Exception:
        return 0

def add_dim_count(counter, emb):
    dim = embedding_dim_of(emb)
    counter[dim] = counter.get(dim, 0) + 1

def ckpt_state_index_lookup():
    lookup = {}
    for st, idx in (ckpt.get("state2idx", {}) or {}).items():
        try:
            lookup[tuple(st)] = int(idx)
        except Exception:
            continue
    return lookup

def ckpt_state_key_samples(limit=5):
    state2idx = ckpt.get("state2idx", {}) or {}
    samples = []
    for key in list(state2idx.keys())[:limit]:
        try:
            tuple_repr = short_state_repr(tuple(key))
        except Exception:
            tuple_repr = None
        samples.append({
            "type": type(key).__name__,
            "repr": short_state_repr(key),
            "tuple_repr": tuple_repr,
        })
    return samples

def deterministic_embedding_for_state(state_tuple, dim=8):
    vec = np.zeros(dim, dtype=np.float32)
    for i, token in enumerate(state_tuple):
        bucket = abs(hash(str(token))) % dim
        vec[bucket] += 1.0 / (i + 1)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()

def safe_metric_scalar(value, max_val=50.0):
    if isinstance(value, torch.Tensor):
        value = float(value.detach().cpu().item())
    try:
        value = float(value)
    except Exception:
        return 0.0
    if not np.isfinite(value):
        return max_val
    return float(min(max(value, 0.0), max_val))

def local_cluster_compactness(X_np, labels):
    labels = np.asarray(labels, dtype=np.int64)
    X = np.asarray(X_np, dtype=np.float32)
    if len(labels) == 0:
        return np.asarray([], dtype=np.float32)

    local_k = int(labels.max()) + 1
    compact = np.zeros(local_k, dtype=np.float32)
    for k in range(local_k):
        idx = np.where(labels == k)[0]
        if len(idx) == 0:
            continue
        center = X[idx].mean(axis=0)
        dists = np.linalg.norm(X[idx] - center, axis=1)
        compact[k] = float(np.mean(dists)) if len(dists) else 0.0

    mean = float(np.mean(compact[compact > 0])) if np.any(compact > 0) else 1.0
    return compact / (mean + 1e-6)

def kl_proxy_state_cluster_nstep_local(
    local_state_idx,
    local_cluster_idx,
    global_state_indices,
    out_neighbors,
    labels,
    pi_state,
    steps=3,
    k_per_step=50,
    eps=1e-8,
    clamp_max=50.0,
):
    if (
        global_state_indices is None
        or out_neighbors is None
        or pi_state is None
        or local_state_idx < 0
        or local_state_idx >= len(global_state_indices)
    ):
        return 0.0

    labels = np.asarray(labels, dtype=np.int64)
    global_state_indices = np.asarray(global_state_indices, dtype=np.int64)
    if len(labels) != len(global_state_indices):
        return 0.0

    s_global = int(global_state_indices[local_state_idx])
    if s_global < 0 or s_global >= len(out_neighbors):
        return 0.0

    def safe_norm_dict(d):
        total = float(sum(d.values()))
        if total <= eps:
            return {}
        return {int(k): float(v) / (total + eps) for k, v in d.items() if float(v) > 0}

    def expand_step(prob_dict):
        next_dict = {}
        for j, weight in prob_dict.items():
            if weight <= 0 or int(j) < 0 or int(j) >= len(out_neighbors):
                continue
            for k, prob in out_neighbors[int(j)]:
                value = weight * float(prob)
                if value <= 0:
                    continue
                k = int(k)
                next_dict[k] = next_dict.get(k, 0.0) + value

        if len(next_dict) > k_per_step:
            next_dict = dict(sorted(next_dict.items(), key=lambda item: item[1], reverse=True)[:k_per_step])
        return safe_norm_dict(next_dict)

    ps_dict = {s_global: 1.0}
    pc_dict = {}
    members = np.where(labels == int(local_cluster_idx))[0]
    if members.size == 0:
        return clamp_max

    for local_idx in members:
        gidx = int(global_state_indices[int(local_idx)])
        if gidx < 0 or gidx >= len(pi_state):
            continue
        weight = float(pi_state[gidx])
        if weight > 0:
            pc_dict[gidx] = pc_dict.get(gidx, 0.0) + weight
    pc_dict = safe_norm_dict(pc_dict)
    if not pc_dict:
        return clamp_max

    for _ in range(steps):
        ps_dict = expand_step(ps_dict)
        pc_dict = expand_step(pc_dict)
        if not ps_dict:
            return 0.0

    keys = list(ps_dict.keys())
    ps = np.asarray([ps_dict.get(k, 0.0) for k in keys], dtype=np.float64)
    pc = np.asarray([pc_dict.get(k, 0.0) for k in keys], dtype=np.float64)
    ps = ps / (ps.sum() + eps)
    pc = np.maximum(pc / (pc.sum() + eps), eps)
    ps = np.maximum(ps, eps)
    value = float(np.sum(ps * (np.log(ps) - np.log(pc))))
    return safe_metric_scalar(value, max_val=clamp_max)

def fallback_local_cluster_count(num_states):
    if num_states <= 1:
        return 1
    return max(2, min(12, int(round(np.sqrt(num_states)))))

def estimate_cluster_count_from_next_steps(state_next_counts, max_k=20):
    rows = []
    events = sorted({
        str(event)
        for counts in (state_next_counts or {}).values()
        for event, value in counts.items()
        if float(value) > 0
    })
    if not state_next_counts or not events:
        return None, {"source": "fallback_sqrt", "reason": "no next-step counts"}

    skipped_no_outgoing = 0
    for counts in state_next_counts.values():
        total = count_total(counts)
        if total <= 0:
            skipped_no_outgoing += 1
            continue
        else:
            rows.append([float(counts.get(event, 0.0)) / total for event in events])

    X = np.asarray(rows, dtype=np.float32)
    num_states = int(X.shape[0])
    if num_states <= 1:
        return 1, {"source": "next_step_behavior", "reason": "single state"}

    unique_rows = np.unique(np.round(X, decimals=6), axis=0)
    unique_count = int(unique_rows.shape[0])
    if unique_count <= 1:
        return 1, {
            "source": "next_step_behavior",
            "reason": "all states have the same next-step distribution",
            "next_event_count": len(events),
            "states_without_next_step": skipped_no_outgoing,
        }

    max_candidate = min(int(max_k), num_states, unique_count)
    if max_candidate < 2:
        return 1, {"source": "next_step_behavior", "reason": "too few behavior groups"}

    best_k = 2
    best_score = -float("inf")
    candidates = []
    for k in range(2, max_candidate + 1):
        labels = KMeans(n_clusters=k, random_state=0, n_init=10).fit_predict(X)
        unique_labels, counts = np.unique(labels, return_counts=True)
        if len(unique_labels) < 2:
            continue
        try:
            silhouette = float(silhouette_score(X, labels, metric="euclidean"))
        except Exception:
            continue
        singleton_count = int(np.sum(counts == 1))
        score = silhouette - 0.02 * k - 0.08 * singleton_count
        candidates.append({
            "k": int(k),
            "silhouette": silhouette,
            "singleton_count": singleton_count,
            "score": float(score),
        })
        if score > best_score:
            best_score = score
            best_k = int(k)

    if not candidates:
        return None, {"source": "fallback_sqrt", "reason": "no valid silhouette candidate"}

    if best_score < 0.05:
        return 1, {
            "source": "next_step_behavior",
            "reason": "weak next-step separation",
            "best_score": float(best_score),
            "next_event_count": len(events),
            "states_without_next_step": skipped_no_outgoing,
            "candidates": candidates,
        }

    return best_k, {
        "source": "next_step_behavior",
        "reason": "selected by next-step distribution silhouette",
        "best_score": float(best_score),
        "next_event_count": len(events),
        "unique_behavior_count": unique_count,
        "states_without_next_step": skipped_no_outgoing,
        "candidates": candidates,
    }

def choose_local_cluster_count(num_states, requested=None, state_next_counts=None, return_info=False):
    if num_states <= 1:
        result = 1
        info = {"source": "trivial", "reason": "num_states <= 1"}
    elif requested is not None:
        try:
            result = max(1, min(int(requested), num_states))
            info = {"source": "user_requested", "reason": "manual cluster count"}
        except Exception:
            result = fallback_local_cluster_count(num_states)
            info = {"source": "fallback_sqrt", "reason": "invalid manual cluster count"}
    else:
        estimated, info = estimate_cluster_count_from_next_steps(state_next_counts)
        if estimated is None:
            result = fallback_local_cluster_count(num_states)
            info = {
                **(info or {}),
                "source": "fallback_sqrt",
                "fallback_value": int(result),
            }
        else:
            result = max(1, min(int(estimated), num_states))
            info = {
                **(info or {}),
                "estimated_value": int(result),
            }

    return (result, info) if return_info else result

def count_total(counts):
    return sum(float(v) for v in counts.values())

def counts_entropy(counts):
    total = count_total(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    h = 0.0
    for value in counts.values():
        p = float(value) / total
        if p > 0:
            h -= p * np.log2(p)
    return float(h / np.log2(len(counts)))

def kl_from_counts(source_counts, baseline_counts):
    source_total = count_total(source_counts)
    baseline_total = count_total(baseline_counts)
    if source_total <= 0 or baseline_total <= 0:
        return 0.0

    keys = set(source_counts.keys()) | set(baseline_counts.keys())
    if not keys:
        return 0.0

    epsilon = 1e-6
    smooth_denominator = 1.0 + epsilon * len(keys)
    value = 0.0
    for key in keys:
        pv = ((float(source_counts.get(key, 0)) / source_total) + epsilon) / smooth_denominator
        qv = ((float(baseline_counts.get(key, 0)) / baseline_total) + epsilon) / smooth_denominator
        value += pv * np.log2(pv / qv)

    if abs(value) < 1e-10:
        return 0.0
    return float(max(0.0, value))

def build_state_next_counts(selected, full_order_states, K):
    full_state_set = set(full_order_states)
    state_next_counts = {st: Counter() for st in full_order_states}
    state_occurrences = {st: 0 for st in full_order_states}

    for _, seq in selected:
        for t in range(K - 1, len(seq)):
            st = tuple(seq[t - K + 1:t + 1])
            if st not in full_state_set:
                continue
            state_occurrences[st] += 1
            if t + 1 < len(seq):
                state_next_counts[st][str(seq[t + 1])] += 1

    return state_next_counts, state_occurrences

def evaluate_local_labels(labels, full_order_states, state_next_counts, state_occurrences, X=None):
    labels = np.asarray(labels, dtype=np.int64)
    cluster_state_indices = defaultdict(list)
    for i, label in enumerate(labels):
        cluster_state_indices[int(label)].append(i)

    cluster_next_counts = {}
    for label, indices in cluster_state_indices.items():
        counts = Counter()
        for i in indices:
            counts.update(state_next_counts.get(full_order_states[i], Counter()))
        cluster_next_counts[label] = counts

    member_kl_values = []
    weighted_member_kl_sum = 0.0
    weighted_member_kl_weight = 0.0
    outgoing_member_count = 0
    for i, label in enumerate(labels):
        st = full_order_states[i]
        member_counts = state_next_counts.get(st, Counter())
        member_total = count_total(member_counts)
        if member_total <= 0:
            continue
        outgoing_member_count += 1
        divergence = kl_from_counts(member_counts, cluster_next_counts.get(int(label), Counter()))
        member_kl_values.append(divergence)
        weighted_member_kl_sum += divergence * member_total
        weighted_member_kl_weight += member_total

    cluster_entropy_values = []
    weighted_cluster_entropy_sum = 0.0
    weighted_cluster_entropy_weight = 0.0
    transition_count = 0.0
    for label, counts in cluster_next_counts.items():
        total = count_total(counts)
        transition_count += total
        if total <= 0:
            continue
        ent = counts_entropy(counts)
        cluster_entropy_values.append(ent)
        weighted_cluster_entropy_sum += ent * total
        weighted_cluster_entropy_weight += total

    compactness_values = []
    weighted_compactness_sum = 0.0
    weighted_compactness_weight = 0
    if X is not None and len(labels) > 0:
        X_np = np.asarray(X, dtype=np.float32)
        for _, indices in cluster_state_indices.items():
            if not indices:
                continue
            points = X_np[indices]
            center = points.mean(axis=0)
            dists = np.linalg.norm(points - center, axis=1)
            compactness = float(dists.mean()) if len(dists) else 0.0
            compactness_values.append(compactness)
            weighted_compactness_sum += compactness * len(indices)
            weighted_compactness_weight += len(indices)

    cluster_sizes = {
        str(label): len(indices)
        for label, indices in sorted(cluster_state_indices.items())
    }
    singleton_count = sum(1 for size in cluster_sizes.values() if size == 1)

    return {
        "cluster_count": int(len(cluster_state_indices)),
        "cluster_sizes": cluster_sizes,
        "singleton_count": int(singleton_count),
        "min_cluster_size": int(min(cluster_sizes.values())) if cluster_sizes else 0,
        "max_cluster_size": int(max(cluster_sizes.values())) if cluster_sizes else 0,
        "avg_member_kl": float(np.mean(member_kl_values)) if member_kl_values else 0.0,
        "weighted_avg_member_kl": (
            float(weighted_member_kl_sum / weighted_member_kl_weight)
            if weighted_member_kl_weight > 0 else 0.0
        ),
        "avg_cluster_entropy": float(np.mean(cluster_entropy_values)) if cluster_entropy_values else 0.0,
        "weighted_avg_cluster_entropy": (
            float(weighted_cluster_entropy_sum / weighted_cluster_entropy_weight)
            if weighted_cluster_entropy_weight > 0 else 0.0
        ),
        "avg_embedding_compactness": float(np.mean(compactness_values)) if compactness_values else 0.0,
        "weighted_avg_embedding_compactness": (
            float(weighted_compactness_sum / weighted_compactness_weight)
            if weighted_compactness_weight > 0 else 0.0
        ),
        "member_with_outgoing_count": int(outgoing_member_count),
        "transition_count": int(transition_count),
        "state_occurrence_count": int(sum(state_occurrences.values())),
    }

def compare_local_quality(before, after, before_labels, after_labels):
    before_labels = np.asarray(before_labels, dtype=np.int64)
    after_labels = np.asarray(after_labels, dtype=np.int64)
    moved_count = int(np.sum(before_labels != after_labels)) if len(before_labels) == len(after_labels) else 0

    def delta(key):
        return float(after.get(key, 0.0) - before.get(key, 0.0))

    return {
        "moved_state_count": moved_count,
        "moved_state_ratio": float(moved_count / len(after_labels)) if len(after_labels) else 0.0,
        "delta_singleton_count": int(after.get("singleton_count", 0) - before.get("singleton_count", 0)),
        "delta_cluster_count": int(after.get("cluster_count", 0) - before.get("cluster_count", 0)),
        "delta_avg_member_kl": delta("avg_member_kl"),
        "delta_weighted_avg_member_kl": delta("weighted_avg_member_kl"),
        "delta_avg_cluster_entropy": delta("avg_cluster_entropy"),
        "delta_weighted_avg_cluster_entropy": delta("weighted_avg_cluster_entropy"),
        "delta_avg_embedding_compactness": delta("avg_embedding_compactness"),
        "delta_weighted_avg_embedding_compactness": delta("weighted_avg_embedding_compactness"),
    }

def should_accept_policy_refine(before, after, comparison):
    if before is None or after is None or comparison is None:
        return False, "missing quality metrics"

    delta_weighted_kl = comparison.get("delta_weighted_avg_member_kl", 0.0)
    delta_compact = comparison.get("delta_weighted_avg_embedding_compactness", 0.0)
    delta_singleton = comparison.get("delta_singleton_count", 0)
    delta_cluster_count = comparison.get("delta_cluster_count", 0)

    if delta_cluster_count != 0:
        return False, f"cluster count changed by {delta_cluster_count}"
    if delta_singleton > 0:
        return False, f"singleton count increased by {delta_singleton}"
    if delta_weighted_kl > 1e-6:
        return False, f"weighted KL worsened by {delta_weighted_kl:.6f}"
    if delta_compact > 0.05:
        return False, f"embedding compactness worsened by {delta_compact:.6f}"

    return True, "accepted"

def json_safe(value):
    if isinstance(value, dict):
        return {str(json_safe(k)): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    return value

def refine_local_labels_with_policy(
    X_np,
    labels,
    refine_steps=4,
    global_state_indices=None,
    out_neighbors=None,
    pi_state=None,
):
    if refine_steps <= 0:
        return labels

    device = next(policy_net.parameters()).device
    X = torch.tensor(X_np, dtype=torch.float32, device=device)
    X_cpu = np.asarray(X_np, dtype=np.float32)
    labels = np.asarray(labels, dtype=np.int64).copy()
    n = len(labels)
    local_k = int(labels.max()) + 1 if n else 0
    if n <= 1 or local_k <= 1:
        return labels

    policy_net.eval()

    for _ in range(refine_steps):
        sizes = np.bincount(labels, minlength=local_k)
        max_size = max(1, int(2 * n / local_k))
        moved_out = np.zeros(local_k, dtype=np.int64)
        max_out = np.maximum(1, (sizes / 8).astype(int))

        centers = []
        for k in range(local_k):
            idx = np.where(labels == k)[0]
            if len(idx) == 0:
                centers.append(torch.zeros_like(X[0]))
            else:
                centers.append(X[idx.tolist()].mean(0))
        centers = torch.stack(centers, dim=0)

        compactness = local_cluster_compactness(X_cpu, labels)
        sizes_t = torch.tensor(sizes, dtype=torch.float32, device=device)
        compact_t = torch.tensor(compactness, dtype=torch.float32, device=device)
        planned_out = np.zeros(local_k, dtype=np.int64)
        n_actions = 0
        n_noop = 0
        n_move = 0

        order = np.arange(n)
        np.random.shuffle(order)

        for i in order:
            cur_c = int(labels[i])
            if sizes[cur_c] - planned_out[cur_c] <= 1:
                continue

            n_actions += 1
            s = X[i]
            dists = torch.norm(centers - s.unsqueeze(0), dim=1)
            cand_idx = torch.topk(dists, k=local_k, largest=False).indices
            if cur_c not in cand_idx:
                cand_idx[-1] = cur_c

            cand_centers = centers[cand_idx]
            cand_dist = dists[cand_idx]
            cand_logsz = torch.log(sizes_t[cand_idx] + 1.0)
            cand_comp = compact_t[cand_idx]

            mu_cur = centers[cur_c]
            cur_dist = dists[cur_c]
            cur_logsz = torch.log(sizes_t[cur_c] + 1.0)
            cur_comp = compact_t[cur_c]
            noop_mask = (cand_idx == cur_c).float()
            planned_out_frac = float(planned_out[cur_c]) / max(float(sizes[cur_c]), 1.0)
            batch_stats = torch.tensor(
                [
                    float(n_move) / max(float(n_actions), 1.0),
                    float(n_noop) / max(float(n_actions), 1.0),
                    planned_out_frac,
                ],
                dtype=torch.float32,
                device=device,
            )
            kl_cur = torch.tensor(
                kl_proxy_state_cluster_nstep_local(
                    i,
                    cur_c,
                    global_state_indices,
                    out_neighbors,
                    labels,
                    pi_state,
                ),
                dtype=torch.float32,
                device=device,
            )
            kl_cand = torch.tensor(
                [
                    kl_proxy_state_cluster_nstep_local(
                        i,
                        int(c.item()),
                        global_state_indices,
                        out_neighbors,
                        labels,
                        pi_state,
                    )
                    for c in cand_idx
                ],
                dtype=torch.float32,
                device=device,
            )

            with torch.no_grad():
                logits, _, _ = policy_net(
                    s=s,
                    mu_cur=mu_cur,
                    cand_centers=cand_centers,
                    cand_logsz=cand_logsz,
                    cand_comp=cand_comp,
                    cand_dist=cand_dist,
                    cur_logsz=cur_logsz,
                    cur_comp=cur_comp,
                    cur_dist=cur_dist,
                    kl_cur=kl_cur,
                    kl_cand=kl_cand,
                    noop_mask=noop_mask,
                    batch_stats=batch_stats,
                )
                logits = torch.nan_to_num(logits, nan=-1e9, posinf=-1e9, neginf=-1e9)
                logits = logits - logits.max()
                probs = F.softmax(logits / 3, dim=0)
                if (not torch.isfinite(probs).all()) or probs.sum() <= 0:
                    probs = torch.ones_like(probs) / probs.numel()

            choice = torch.multinomial(probs, 1).item()
            new_c = int(cand_idx[choice].item())
            if new_c == cur_c:
                n_noop += 1
                continue
            if sizes[cur_c] <= 1 or sizes[cur_c] - planned_out[cur_c] <= 1:
                continue
            if moved_out[cur_c] >= max_out[cur_c]:
                continue
            if sizes[new_c] >= max_size:
                continue

            labels[i] = new_c
            planned_out[cur_c] += 1
            moved_out[cur_c] += 1
            sizes[cur_c] -= 1
            sizes[new_c] += 1
            n_move += 1

    # Keep labels compact/stable after possible empty clusters.
    unique = sorted(set(int(x) for x in labels))
    remap = {old: new for new, old in enumerate(unique)}
    return np.asarray([remap[int(x)] for x in labels], dtype=np.int64)

def build_region_model_payload(seq_indices=None, n_clusters=None, K=DEFAULT_K, refine_steps=4, first_order_sequences=None):
    if CURRENT_PAYLOAD is None:
        raise ValueError("No payload loaded")

    payload_first_order_sequences = CURRENT_PAYLOAD.get("first_order_sequences", []) or []
    original_sequence_ids = CURRENT_PAYLOAD.get("sequence_ids", []) or []

    selected = []
    if first_order_sequences is not None:
        for i, seq in enumerate(first_order_sequences):
            if not isinstance(seq, list) or len(seq) == 0:
                continue
            selected.append((int(i), [str(x) for x in seq]))
    else:
        for idx in seq_indices or []:
            i = int(idx)
            if i < 0 or i >= len(payload_first_order_sequences):
                continue
            seq = payload_first_order_sequences[i]
            if not isinstance(seq, list) or len(seq) == 0:
                continue
            original_id = original_sequence_ids[i] if i < len(original_sequence_ids) else i
            selected.append((int(original_id), [str(x) for x in seq]))

    if not selected:
        raise ValueError("No valid sequences for local rebuild")

    unique_states = []
    seen = set()
    for _, seq in selected:
        for t in range(len(seq)):
            start = max(0, t - K + 1)
            st = tuple(seq[start:t + 1])
            if st not in seen:
                seen.add(st)
                unique_states.append(st)

    full_order_states = [st for st in unique_states if len(st) == K]
    warmup_states = [st for st in unique_states if len(st) < K]
    state_next_counts, state_occurrences = build_state_next_counts(selected, full_order_states, K)
    requested_clusters_raw = n_clusters
    requested_clusters, cluster_count_selection = choose_local_cluster_count(
        len(full_order_states),
        n_clusters,
        state_next_counts=state_next_counts,
        return_info=True,
    )

    ckpt_lookup = state_embedding_lookup_from_ckpt()
    ckpt_index_lookup = ckpt_state_index_lookup()
    ckpt_out_neighbors = ckpt.get("out_neighbors", None)
    ckpt_pi_state = ckpt.get("pi_state", None)

    embedding_debug = {
        "ckpt_lookup_size": len(ckpt_lookup),
        "ckpt_state_key_samples": ckpt_state_key_samples(),
        "unique_state_count": len(unique_states),
        "full_order_state_count": len(full_order_states),
        "warmup_state_count": len(warmup_states),
        "unique_sources": {"ckpt": 0, "fallback": 0},
        "full_order_sources": {"ckpt": 0, "fallback": 0},
        "unique_dim_counts": {},
        "full_order_dim_counts": {},
        "full_order_missing_ckpt_samples": [],
        "structure_features": {
            "out_neighbors_available": ckpt_out_neighbors is not None,
            "pi_state_available": ckpt_pi_state is not None,
            "global_state_indices_available": False,
        },
    }

    for st in unique_states:
        if st in ckpt_lookup:
            model_emb = ckpt_lookup[st]
            embedding_debug["unique_sources"]["ckpt"] += 1
        else:
            model_emb = deterministic_embedding_for_state(st, dim=state_dim)
            embedding_debug["unique_sources"]["fallback"] += 1

        add_dim_count(embedding_debug["unique_dim_counts"], model_emb)

    full_model_embeddings = []
    full_global_state_indices = []
    for st in full_order_states:
        if st in ckpt_lookup:
            model_emb = ckpt_lookup[st]
            embedding_debug["full_order_sources"]["ckpt"] += 1
        else:
            if len(embedding_debug["full_order_missing_ckpt_samples"]) < 8:
                embedding_debug["full_order_missing_ckpt_samples"].append(short_state_repr(st))
            model_emb = deterministic_embedding_for_state(st, dim=state_dim)
            embedding_debug["full_order_sources"]["fallback"] += 1

        add_dim_count(embedding_debug["full_order_dim_counts"], model_emb)
        full_model_embeddings.append(np.asarray(model_emb, dtype=np.float32))
        full_global_state_indices.append(int(ckpt_index_lookup.get(st, -1)))

    embedding_debug["structure_features"]["global_state_indices_available"] = all(
        idx >= 0 for idx in full_global_state_indices
    )

    print("[ReAggregate Debug]", json.dumps(json_safe({
        "selected_sequences": len(selected),
        "requested_clusters": requested_clusters_raw,
        "effective_requested_clusters": requested_clusters,
        "policy_state_dim": state_dim,
        **embedding_debug,
    }), ensure_ascii=False))

    embedding_dim = 0
    labels = np.asarray([], dtype=np.int64)
    actual_visible_clusters = 0
    quality_info = {
        "before_refine": None,
        "after_refine": None,
        "comparison": None,
        "refine_accepted": False,
        "refine_accept_reason": None,
    }

    refine_method = "skipped"
    refine_note = None
    if len(full_order_states) == 0:
        refine_note = "No full-order states available for visible clustering"
    else:
        # KMeans needs a rectangular matrix; if fallback dimensions differ, pad to max dim.
        max_dim = max(len(v) for v in full_model_embeddings)
        X = np.zeros((len(full_model_embeddings), max_dim), dtype=np.float32)
        for i, emb in enumerate(full_model_embeddings):
            X[i, :len(emb)] = emb
        embedding_dim = int(X.shape[1])

        if requested_clusters <= 1:
            labels = np.zeros(len(full_order_states), dtype=int)
        else:
            labels = KMeans(n_clusters=requested_clusters, random_state=0, n_init=10).fit_predict(X)

        kmeans_labels = np.asarray(labels, dtype=np.int64).copy()
        quality_info["before_refine"] = evaluate_local_labels(
            kmeans_labels,
            full_order_states,
            state_next_counts,
            state_occurrences,
            X=X,
        )

        ckpt_full_order_count = embedding_debug["full_order_sources"]["ckpt"]
        all_full_order_from_ckpt = ckpt_full_order_count == len(full_order_states)

        if refine_steps > 0 and embedding_dim == state_dim and requested_clusters > 1 and all_full_order_from_ckpt:
            try:
                labels = refine_local_labels_with_policy(
                    X,
                    labels,
                    refine_steps=refine_steps,
                    global_state_indices=full_global_state_indices,
                    out_neighbors=ckpt_out_neighbors,
                    pi_state=ckpt_pi_state,
                )
                refine_method = "policy_net"
            except Exception as e:
                refine_note = f"policy_net skipped: {str(e)}"
        elif refine_steps > 0 and embedding_dim == state_dim and requested_clusters > 1:
            refine_note = (
                "policy_net skipped: local embeddings are not fully from ckpt "
                f"({ckpt_full_order_count}/{len(full_order_states)} full-order states matched ckpt)"
            )
        elif refine_steps > 0:
            refine_note = f"policy_net skipped: embedding dim {embedding_dim} != policy dim {state_dim}"

        quality_info["after_refine"] = evaluate_local_labels(
            labels,
            full_order_states,
            state_next_counts,
            state_occurrences,
            X=X,
        )
        quality_info["comparison"] = compare_local_quality(
            quality_info["before_refine"],
            quality_info["after_refine"],
            kmeans_labels,
            labels,
        )

        if refine_method == "policy_net":
            accepted, reason = should_accept_policy_refine(
                quality_info["before_refine"],
                quality_info["after_refine"],
                quality_info["comparison"],
            )
            quality_info["refine_accepted"] = bool(accepted)
            quality_info["refine_accept_reason"] = reason
            if not accepted:
                labels = kmeans_labels.copy()
                refine_method = "policy_net_rejected"
                refine_note = f"policy_net rejected: {reason}"
        else:
            quality_info["refine_accept_reason"] = refine_note or "policy_net not applied"

        print("[ReAggregate Quality]", json.dumps(json_safe({
            "refine": refine_method,
            "refine_note": refine_note,
            **quality_info,
        }), ensure_ascii=False))

        actual_visible_clusters = int(len(set(int(x) for x in labels)))

    state_to_cluster = {
        st: int(labels[i])
        for i, st in enumerate(full_order_states)
    }
    for st in warmup_states:
        state_to_cluster[st] = -1

    rows = []
    local_sequence_id = 0
    for original_id, seq in selected:
        for t, ev in enumerate(seq):
            start = max(0, t - K + 1)
            st = tuple(seq[start:t + 1])
            rows.append({
                "sequence_id": local_sequence_id,
                "original_sequence_id": original_id,
                "timestep": t,
                "first_order_node": str(ev),
                "raw_event": str(ev),
                "high_order_state": st,
                "semantic_class": state_to_cluster[st],
            })
        local_sequence_id += 1

    df = pd.DataFrame(rows)
    df.attrs["max_order"] = K
    payload = build_payload(df)
    payload["model_info"] = {
        "scope": "region",
        "source_seq_count": len(selected),
        "source_seq_ids": [sid for sid, _ in selected],
        "num_states": len(unique_states),
        "num_full_order_states": len(full_order_states),
        "num_warmup_states": len(warmup_states),
        "requested_clusters": int(requested_clusters_raw) if requested_clusters_raw is not None else int(requested_clusters),
        "effective_requested_clusters": int(requested_clusters),
        "cluster_count_selection": cluster_count_selection,
        "num_clusters": int(actual_visible_clusters),
        "actual_visible_clusters": int(actual_visible_clusters),
        "K": int(K),
        "init": "kmeans",
        "refine": refine_method,
        "refine_steps": int(refine_steps),
        "refine_note": refine_note,
        "embedding_dim": int(embedding_dim),
        "embedding_debug": embedding_debug,
        "quality": quality_info,
    }
    return payload

def refine_cluster(map_df, class_id, new_K, policy_net, ckpt, refine_steps=4):
    import numpy as np
    import pandas as pd
    from sklearn.cluster import KMeans

    # ========= embedding =========
    state_embed = ckpt["state_embeds"]

    if isinstance(state_embed, torch.Tensor):
        state_embed = state_embed.detach().cpu().numpy()
    else:
        state_embed = np.asarray(state_embed, dtype=np.float32)

    map_df = map_df.copy()
    if "state_tuple" not in map_df.columns:
        map_df["state_tuple"] = map_df["state"].apply(parse_state)

    if "state_id" not in map_df.columns:
        ckpt_index_lookup = ckpt_state_index_lookup()
        map_df["state_id"] = map_df["state_tuple"].map(lambda st: ckpt_index_lookup.get(tuple(st), -1))

    mask = map_df["cluster_id"] == class_id
    sub_df = map_df[mask].copy()
    other_df = map_df[~mask].copy()

    if len(sub_df) == 0:
        raise ValueError("class not found")

    state_ids = sub_df["state_id"].values.astype(int)
    if np.any(state_ids < 0) or np.any(state_ids >= len(state_embed)):
        missing = sub_df.loc[(sub_df["state_id"] < 0) | (sub_df["state_id"] >= len(state_embed)), "state_tuple"] \
            .head(5) \
            .map(short_state_repr) \
            .tolist()
        raise ValueError(f"Cannot split node: states missing from checkpoint embeddings: {missing}")

    X_np = np.asarray(state_embed[state_ids], dtype=np.float32)
    embedding_dim = int(X_np.shape[1]) if X_np.ndim == 2 else 0
    n = len(X_np)

    if new_K > n:
        new_K = n

    if new_K <= 1:
        raise ValueError("new_K must >= 2")

    # =========================
    # KMeans init
    # =========================
    kmeans = KMeans(
        n_clusters=new_K,
        random_state=0,
        n_init=10
    )

    labels = kmeans.fit_predict(X_np).copy()
    kmeans_labels = np.asarray(labels, dtype=np.int64).copy()

    full_order_states = [tuple(st) for st in sub_df["state_tuple"].tolist()]
    selected_sequences = [
        (sid, seq)
        for sid, seq in enumerate((CURRENT_PAYLOAD or {}).get("first_order_sequences", []) or [])
        if isinstance(seq, list) and seq
    ]
    state_next_counts, state_occurrences = build_state_next_counts(selected_sequences, full_order_states, DEFAULT_K)

    quality_info = {
        "refine": "skipped",
        "refine_note": None,
        "before_refine": evaluate_local_labels(
            kmeans_labels,
            full_order_states,
            state_next_counts,
            state_occurrences,
            X=X_np,
        ),
        "after_refine": None,
        "comparison": None,
        "refine_accepted": False,
        "refine_accept_reason": None,
        "embedding_dim": int(embedding_dim),
        "policy_state_dim": int(state_dim),
    }

    ckpt_out_neighbors = ckpt.get("out_neighbors", None)
    ckpt_pi_state = ckpt.get("pi_state", None)
    if refine_steps > 0 and embedding_dim == state_dim and new_K > 1:
        refined_labels = refine_local_labels_with_policy(
            X_np,
            kmeans_labels,
            refine_steps=refine_steps,
            global_state_indices=state_ids,
            out_neighbors=ckpt_out_neighbors,
            pi_state=ckpt_pi_state,
        )
        quality_info["refine"] = "policy_net"
        quality_info["after_refine"] = evaluate_local_labels(
            refined_labels,
            full_order_states,
            state_next_counts,
            state_occurrences,
            X=X_np,
        )
        quality_info["comparison"] = compare_local_quality(
            quality_info["before_refine"],
            quality_info["after_refine"],
            kmeans_labels,
            refined_labels,
        )
        accepted, reason = should_accept_policy_refine(
            quality_info["before_refine"],
            quality_info["after_refine"],
            quality_info["comparison"],
        )
        quality_info["refine_accepted"] = bool(accepted)
        quality_info["refine_accept_reason"] = reason
        if accepted:
            labels = refined_labels
        else:
            labels = kmeans_labels
            quality_info["refine"] = "policy_net_rejected"
            quality_info["refine_note"] = f"policy_net rejected: {reason}"
    elif refine_steps > 0:
        quality_info["refine_note"] = f"policy_net skipped: embedding dim {embedding_dim} != policy dim {state_dim}"
        quality_info["refine_accept_reason"] = quality_info["refine_note"]

    # =========================
    # map back
    # =========================
    max_id = int(map_df["cluster_id"].max())
    new_ids = labels + max_id + 1
    sub_df["cluster_id"] = new_ids

    map_df2 = pd.concat([other_df, sub_df], ignore_index=True)

    split_map = {}
    for cid in sorted(set(new_ids)):
        states = map_df2.loc[
            map_df2["cluster_id"] == cid,
            "state_id"
        ].tolist()
        split_map[int(cid)] = list(map(int, states))

    print("[Split Quality]", json.dumps(json_safe(quality_info), ensure_ascii=False))
    return map_df2, split_map, quality_info

# -------------------------
# API
# -------------------------
@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = file.filename.lower()

    if filename.endswith(".xlsx"):
        df = pd.read_excel(file, engine="openpyxl")
    elif filename.endswith(".csv"):
        df = pd.read_csv(file)
    else:
        return jsonify({"error": "Unsupported file type"}), 400

    try:
        payload = build_payload(df)
        set_current_df(df)
        set_current_payload(payload)
    except Exception as e:
        return jsonify({
            "error": "Failed to parse file",
            "detail": str(e)
        }), 500

    return jsonify(payload)

@app.route("/api/rewrite", methods=["POST"])
def rewrite_api():

    if "cluster_file" not in request.files:
        return jsonify({"error": "No cluster file", "detail": "请上传 state_cluster 的 CSV 文件"}), 400

    file = request.files["cluster_file"]
    if file.filename == "":
        return jsonify({"error": "Empty file", "detail": "未选择文件"}), 400

    filename = (file.filename or "").lower()
    if not filename.endswith(".csv"):
        return jsonify({"error": "Unsupported file type", "detail": "仅支持 .csv 文件"}), 400

    # K = int(request.form.get("K", DEFAULT_K))
    K = 3

    fd, tmp_path = tempfile.mkstemp(suffix=".csv")
    try:
        os.close(fd)
        file.save(tmp_path)

        map_df = pd.read_csv(tmp_path)

        for col in ["state", "cluster_id"]:
            if col not in map_df.columns:
                return jsonify({
                    "error": "Invalid CSV",
                    "detail": f"CSV 必须包含列: state, cluster_id，缺少: {col}"
                }), 400

        set_current_state_map(map_df)

        map_df["state"] = map_df["state"].apply(parse_state)

        df = rewrite_highorder(
            input_xlsx=INPUT_XLSX,
            state_cluster_csv=tmp_path,
            K=K,
        )

        payload = build_payload(df)
        set_current_df(df)
        set_current_payload(payload)
        return jsonify(payload)

    except Exception as e:
        return jsonify({
            "error": "rewrite failed",
            "detail": str(e)
        }), 500
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

@app.route("/api/refine_cluster", methods=["POST"])
def refine_cluster_api():
    if "cluster_file" not in request.files:
        return jsonify({"error": "no file"}), 400

    file = request.files["cluster_file"]

    class_id = int(request.form["class_id"])
    new_K = int(request.form["new_K"])

    fd, tmp = tempfile.mkstemp(suffix=".csv")

    try:
        os.close(fd)
        file.save(tmp)

        map_df = pd.read_csv(tmp)

        # refine
        map_df2, split_map, split_quality = refine_cluster(
            map_df,
            class_id,
            new_K,
            policy_net,
            ckpt
        )

        tmp2 = tmp + "_new.csv"
        map_df2.to_csv(tmp2, index=False)
        set_current_state_map(map_df2)

        df = rewrite_highorder(
            input_xlsx=INPUT_XLSX,
            state_cluster_csv=tmp2,
            K=DEFAULT_K,
        )

        payload = build_payload(df)
        set_current_df(df)

        # ✅ 加 split info
        payload["split_info"] = {
            str(class_id): split_map
        }
        payload["split_quality"] = {
            str(class_id): json_safe(split_quality)
        }
        set_current_payload(payload)

        return jsonify(payload)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        if os.path.exists(tmp):
            os.remove(tmp)

        if os.path.exists(tmp + "_new.csv"):
            os.remove(tmp + "_new.csv")

@app.route("/api/rebuild_region_model", methods=["POST"])
def rebuild_region_model_api():
    body = request.get_json(silent=True) or {}
    seq_ids = body.get("seq_ids", None) or body.get("seqIds", None) or []
    first_order_sequences = body.get("first_order_sequences", None) or body.get("firstOrderSequences", None)
    n_clusters = body.get("n_clusters", None) or body.get("numClusters", None)
    K = int(body.get("K", DEFAULT_K) or DEFAULT_K)
    refine_steps_value = body.get("refine_steps", None)
    if refine_steps_value is None:
        refine_steps_value = body.get("refineSteps", 4)
    refine_steps = int(refine_steps_value)

    has_slice_sequences = isinstance(first_order_sequences, list) and len(first_order_sequences) > 0
    if not has_slice_sequences and (not isinstance(seq_ids, list) or len(seq_ids) == 0):
        return jsonify({
            "error": "No sequences",
            "detail": "seq_ids or first_order_sequences must contain at least one sequence"
        }), 400

    try:
        payload = build_region_model_payload(
            seq_ids,
            n_clusters=n_clusters,
            K=K,
            refine_steps=refine_steps,
            first_order_sequences=first_order_sequences if has_slice_sequences else None
        )
        return jsonify(json_safe(payload))
    except Exception as e:
        return jsonify({
            "error": "region rebuild failed",
            "detail": str(e)
        }), 500

@app.route("/api/filter_sequences", methods=["POST"])
def filter_sequences_api():
    if CURRENT_PAYLOAD is None:
        return jsonify({"error": "No payload loaded", "detail": "请先上传或重写数据"}), 400

    body = request.get_json(silent=True) or {}

    edges = body.get("edges", []) or []
    classes = [str(x) for x in (body.get("classes", []) or [])]
    state_values = [normalize_state_key(x) for x in (body.get("states", []) or [])]
    states = [x for x in state_values if "→" not in x]
    state_transitions = [
        normalize_state_key(x)
        for x in (
            body.get("state_transitions", None)
            or body.get("stateTransitions", None)
            or []
        )
    ]
    state_transitions.extend(x for x in state_values if "→" in x)
    group_logic = body.get("group_logic") or body.get("groupLogic") or {}
    source_seq_ids = body.get("source_seq_ids", None)

    has_edges = len(edges) > 0
    has_classes = len(classes) > 0
    has_states = len(states) > 0
    has_state_transitions = len(state_transitions) > 0

    if not has_edges and not has_classes and not has_states and not has_state_transitions:
        return jsonify({
            "matched_seq_ids": [],
            "highlight_nodes": [],
            "highlight_edges": [],
            "count": 0
        })

    idx = get_filter_index()
    if idx is None:
        return jsonify({"error": "Index unavailable"}), 500

    edge_to_seq_ids = idx["edge_to_seq_ids"]
    class_to_seq_ids = idx["class_to_seq_ids"]
    state_to_seq_ids = idx["state_to_seq_ids"]
    seq_highlights = idx["seq_highlights"]

    group_results = []

    if has_edges:
        group_results.append(
            match_filter_group(edges, group_logic.get("edges", "AND"), edge_to_seq_ids)
        )
    if has_classes:
        group_results.append(
            match_filter_group(classes, group_logic.get("classes", "AND"), class_to_seq_ids)
        )
    if has_states:
        group_results.append(
            match_filter_group(states, group_logic.get("states", "AND"), state_to_seq_ids)
        )
    if has_state_transitions:
        group_results.append(
            match_filter_group(
                state_transitions,
                group_logic.get("stateTransitions", group_logic.get("state_transitions", "AND")),
                state_to_seq_ids
            )
        )

    candidate_seq_ids = combine_seq_sets(group_results, "AND")

    if source_seq_ids is not None:
        source_set = set(int(x) for x in source_seq_ids)
        matched_seq_ids = [sid for sid in candidate_seq_ids if sid in source_set]
    else:
        matched_seq_ids = list(candidate_seq_ids)

    highlight_nodes = set()
    highlight_edges = set()

    for sid in matched_seq_ids:
        feat = seq_highlights.get(sid)
        if not feat:
            continue
        for n in feat["nodes"]:
            highlight_nodes.add(n)
        for e in feat["edges"]:
            highlight_edges.add(e)

    return jsonify({
        "matched_seq_ids": sorted(matched_seq_ids),
        "highlight_nodes": sorted(list(highlight_nodes)),
        "highlight_edges": sorted(list(highlight_edges)),
        "count": len(matched_seq_ids)
    })
# -------------------------
# entry
# -------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        debug=True
    )

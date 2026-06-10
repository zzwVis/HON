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

CKPT_PATH = "model/semantic_agavue_2000_ckpt_seed0.pt"

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

    state2embedding = dict(
        zip(
            map_df["state_tuple"],
            map_df["embedding"]
        )
    )

    state_col = []
    cluster_col = []
    embedding_col = []

    for sid, g in df.groupby("id", sort=False):

        events = g["event"].tolist()

        for t, ev in enumerate(events):

            start = max(0, t-K+1)

            st = tuple(events[start:t+1])

            state_col.append(st)
            cluster_col.append(state2cluster[st])
            embedding_col.append(state2embedding[st])

    df_out = df.copy()

    df_out["high_order_state"] = [
        str(s) for s in state_col
    ]

    df_out["semantic_class"] = cluster_col
    df_out["embedding"] = embedding_col

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

    df["embedding"] = df["embedding"].apply(parse_emb)

    # 最大阶（glyph 对齐用）
    max_L = int(df["high_order_state"].map(len).max() or 1)

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
        # event_seq = collapse_semantic_sequence(seq)
        event_seq = seq

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
    # === 4) Glyph（类 → 多位置分布）【完全不变】 ===
    # =====================================================

    tokens = sorted(
        set(df["first_order_node"].unique().tolist()) | {PLACEHOLDER}
    )

    glyph = {}

    for c, g in df.groupby("semantic_class"):

        pos_counter = [Counter() for _ in range(max_L)]

        # for st in g["high_order_state"]:
        # 去重:不需要考虑这个状态在这个类里面的数量
        for st in set(tuple(x) for x in g["high_order_state"]):
            if len(st) == 0:
                continue
            start = max_L - len(st)
            for j, tok in enumerate(st):
                pos_counter[start + j][clean_tok(tok)] += 1

        pos_dist = []
        for cnt in pos_counter:
            s = sum(cnt.values())
            if s == 0:
                pos_dist.append({t: 0.0 for t in tokens})
            else:
                pos_dist.append({t: cnt.get(t, 0) / s for t in tokens})

        raw_states = [tuple(st) for st in g["high_order_state"].tolist()]

        state2seq = defaultdict(set)

        for st, sid in zip(
                g["high_order_state"],
                g["sequence_id"]
        ):
            state2seq[tuple(st)].add(int(sid))

        unique_states = [list(st) for st in state2seq.keys()]

        supporting_seq_ids = {
            json.dumps(list(st)): sorted(list(sids))
            for st, sids in state2seq.items()
        }

        glyph[int(c)] = {
            "max_order": max_L,
            "position_distributions": pos_dist,
            "raw_states": raw_states, # A-B-B-C
            "unique_states": unique_states,  # set (for detail view)
            "state2seq": supporting_seq_ids  #记录每个高阶状态存在于哪些类中
        }

    # =====================================================
    # === 4.5) High-order-state embedding (scatter)
    # =====================================================
    scatter_rows = []

    for st, g in df.groupby(df["high_order_state"].apply(tuple)):

        embs = []
        for e in g["embedding"].tolist():
            if isinstance(e, list) and len(e) == 2:
                embs.append(e)

        if len(embs) == 0:
            continue

        # 对同一个高阶状态取均值
        mean_xy = np.mean(np.stack(embs), axis=0)

        scatter_rows.append({
            "state": list(st),
            "semantic_class": int(g["semantic_class"].iloc[0]),
            "x": float(mean_xy[0]),
            "y": float(mean_xy[1])
        })

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
        "scatter_states": scatter_rows,
        "state2pos": state2pos_json,
        "max_order": max_L
    }

    return payload

def parse_emb(x):

    if pd.isna(x):
        return None

    # already list
    if isinstance(x, list):
        return x

    # tuple
    if isinstance(x, tuple):
        return list(x)

    # numpy
    if isinstance(x, np.ndarray):
        return x.tolist()

    # torch
    if isinstance(x, torch.Tensor):
        return x.detach().cpu().tolist()

    if isinstance(x, str):

        s = x.strip()

        # case 1: "[0.1, 0.2]"
        if s.startswith("[") and s.endswith("]"):
            return list(map(float, ast.literal_eval(s)))

        # case 2: "0.1;0.2"
        if ";" in s:
            return [float(v) for v in s.split(";")]

        # case 3: "0.1,0.2"
        if "," in s:
            return [float(v) for v in s.split(",")]

    raise ValueError(f"Bad embedding format: {x}")

from sklearn.cluster import KMeans

def refine_cluster(map_df, class_id, new_K, policy_net, ckpt, refine_steps=4):
    import numpy as np
    import pandas as pd
    import torch
    from sklearn.cluster import KMeans

    device = next(policy_net.parameters()).device

    # ========= embedding =========
    state_embed = ckpt["state_embeds"]

    if isinstance(state_embed, torch.Tensor):
        state_embed = state_embed.detach().cpu()

    mask = map_df["cluster_id"] == class_id
    sub_df = map_df[mask].copy()
    other_df = map_df[~mask].copy()

    if len(sub_df) == 0:
        raise ValueError("class not found")

    state_ids = sub_df["state_id"].values.astype(int)
    X = state_embed[state_ids]

    if not isinstance(X, torch.Tensor):
        X = torch.tensor(X, dtype=torch.float32)
    else:
        X = X.float()

    X = X.to(device)
    n = len(X)

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

    labels = kmeans.fit_predict(X.detach().cpu().numpy()).copy()
    policy_net.eval()

    # 全局限制：目标簇最大允许大小
    max_size = int(2 * n / new_K)

    # =========================
    # refine
    # =========================
    for step in range(refine_steps):

        print("\n===== refine step", step, "=====")

        sizes = np.bincount(labels, minlength=new_K)
        print("sizes:", sizes.tolist())

        # 每个cluster每轮最多搬走 1/8
        max_out = np.maximum(1, (sizes / 8).astype(int))
        moved_out = np.zeros(new_K, dtype=np.int64)

        # ---------- centers ----------
        centers = []
        for k in range(new_K):
            idx = np.where(labels == k)[0]
            if len(idx) == 0:
                centers.append(torch.zeros_like(X[0]))
            else:
                centers.append(X[idx].mean(0))
        centers = torch.stack(centers, dim=0)

        # # ---------- compactness ----------
        compactness = np.zeros(new_K, dtype=np.float32)

        # for k in range(new_K):
        #     idx = np.where(labels == k)[0]
        #     if len(idx) <= 1:
        #         compactness[k] = 0
        #     else:
        #         xk = X[idx]
        #         ck = centers[k].unsqueeze(0)
        #         compactness[k] = ((xk - ck) ** 2).sum(1).mean().item()
        #
        # compactness = compactness / (np.mean(compactness) + 1e-6)

        sizes_t = torch.tensor(sizes, dtype=torch.float32, device=device)
        compact_t = torch.tensor(compactness, dtype=torch.float32, device=device)

        order = np.arange(n)
        np.random.shuffle(order)

        planned_out = np.zeros(new_K, dtype=np.int64)

        # =========================
        # iterate states
        # =========================
        for i in order:

            cur_c = int(labels[i])

            # ---- avoid empty cluster ----
            if sizes[cur_c] - planned_out[cur_c] <= 1:
                continue

            s = X[i]

            dists = torch.norm(
                centers - s.unsqueeze(0),
                dim=1
            )

            M = new_K
            top = torch.topk(
                dists,
                k=M,
                largest=False
            ).indices

            if cur_c not in top:
                top[-1] = cur_c

            cand_idx = top
            cand_centers = centers[cand_idx]
            cand_dist = dists[cand_idx]
            cand_logsz = torch.log(sizes_t[cand_idx] + 1.0)
            cand_comp = compact_t[cand_idx]

            mu_cur = centers[cur_c]
            cur_dist = dists[cur_c]
            cur_logsz = torch.log(sizes_t[cur_c] + 1.0)
            cur_comp = compact_t[cur_c]

            kl_cur = torch.zeros(1, device=device, dtype=torch.float32)
            kl_cand = torch.zeros(len(cand_idx), device=device, dtype=torch.float32)

            noop_mask = (cand_idx == cur_c).float()

            # planned_out_frac = (
            #     float(planned_out[cur_c]) / max(float(sizes[cur_c]), 1.0)
            # )
            #
            # batch_stats = torch.tensor(
            #     [0.0, 0.0, planned_out_frac],
            #     dtype=torch.float32,
            #     device=device
            # )

            batch_stats = torch.zeros(3, device=device)

            with torch.no_grad():
                logits, value, ent = policy_net(
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

                logits = logits / 3
                probs = F.softmax(logits, dim=0)

            choice = torch.multinomial(probs, 1).item()
            new_c = int(cand_idx[choice].item())

            # =========================
            # move
            # =========================
            if new_c != cur_c:

                if sizes[cur_c] <= 1:
                    continue

                if sizes[cur_c] - planned_out[cur_c] <= 1:
                    continue

                if moved_out[cur_c] >= max_out[cur_c]:
                    continue

                if sizes[new_c] >= max_size:
                    continue

                effective_cur_size = sizes[cur_c] - planned_out[cur_c]
                ratio = sizes[new_c] / max(1, effective_cur_size)

                if ratio > 2.5:
                    continue

                labels[i] = new_c

                planned_out[cur_c] += 1
                moved_out[cur_c] += 1

                sizes[cur_c] -= 1
                sizes[new_c] += 1

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

    return map_df2, split_map

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

        map_df["state"] = map_df["state"].apply(parse_state)

        for col in ["state", "cluster_id", "embedding"]:
            if col not in map_df.columns:
                return jsonify({
                    "error": "Invalid CSV",
                    "detail": f"CSV 必须包含列: state, cluster_id, embedding，缺少: {col}"
                }), 400

        df = rewrite_highorder(
            input_xlsx=INPUT_XLSX,
            state_cluster_csv=tmp_path,
            K=K,
        )

        payload = build_payload(df)
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
        map_df2, split_map = refine_cluster(
            map_df,
            class_id,
            new_K,
            policy_net,
            ckpt
        )

        tmp2 = tmp + "_new.csv"
        map_df2.to_csv(tmp2, index=False)

        df = rewrite_highorder(
            input_xlsx=INPUT_XLSX,
            state_cluster_csv=tmp2,
            K=DEFAULT_K,
        )

        payload = build_payload(df)

        # ✅ 加 split info
        payload["split_info"] = {
            str(class_id): split_map
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

@app.route("/api/filter_sequences", methods=["POST"])
def filter_sequences_api():
    if CURRENT_PAYLOAD is None:
        return jsonify({"error": "No payload loaded", "detail": "请先上传或重写数据"}), 400

    body = request.get_json(silent=True) or {}

    edges = body.get("edges", []) or []
    classes = [str(x) for x in (body.get("classes", []) or [])]
    states = [normalize_state_key(x) for x in (body.get("states", []) or [])]
    group_logic = body.get("group_logic") or body.get("groupLogic") or {}
    source_seq_ids = body.get("source_seq_ids", None)

    has_edges = len(edges) > 0
    has_classes = len(classes) > 0
    has_states = len(states) > 0

    if not has_edges and not has_classes and not has_states:
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

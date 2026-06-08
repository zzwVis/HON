import torch.nn as nn
import torch
import torch.nn.functional as F

class PolicyNet(nn.Module):
    """
    Actor-Critic PolicyNet for state->cluster decisions.
    """

    def __init__(self, state_dim: int, hidden_dim: int = 128, max_kl: float = 50.0):
        super().__init__()
        self.state_dim = state_dim
        self.hidden_dim = hidden_dim
        self.max_kl = float(max_kl)

        # ===== ★ NEW: scalar encoder to reduce scale-mixing =====
        # scalars_dim: cand_scalars(??) + cur_scalars(4)  -> see _cand_scalar_dim()
        self.scalar_mlp = nn.Sequential(
            nn.Linear(self._cand_scalar_dim(), hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, hidden_dim // 2),
            nn.ReLU(),
        )

        # ===== ★ NEW: scalar → vector gating =====
        self.gate_layer = nn.Linear(self.hidden_dim // 2, 2 * self.state_dim)

        # ---- per-candidate encoder ----
        self.cand_mlp = nn.Sequential(
            nn.Linear(self._cand_feat_dim(), hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

        # # ===== ★ NEW: candidate-level attention =====
        # self.attn_layer = nn.Linear(hidden_dim, 1)
        # actor head
        self.actor_head = nn.Linear(hidden_dim, 1)
        # ===== ★ NEW: multi-head attention =====
        self.num_heads = 4
        self.attn_layer = nn.Linear(hidden_dim, self.num_heads)
        self.attn_proj = nn.Linear(hidden_dim * self.num_heads, hidden_dim)

        # ===== ★ NEW: learnable temperature =====
        self.temperature = nn.Parameter(torch.tensor(1.0))

        # critic head (context-level)
        self.critic_mlp = nn.Sequential(
            nn.Linear(self._ctx_feat_dim(), hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    # ===== ★ MOD: cand scalar dim updated =====
    def _cand_scalar_dim(self) -> int:
        """
        cand_scalars includes:
          base: [cand_dist, cand_logsz, cand_comp, kl_cand] -> 4
          geom: [cos_sc, delta_norm] -> 2
          compare: [delta_kl, delta_dist] -> 2
          noop_flag: [is_noop] -> 1
        total cand = 9

        cur_scalars: [cur_dist, cur_logsz, cur_comp, kl_cur] -> 4

        final scalars concatenated: 9 + 4 = 13
        """
        return 13

    # ===== ★ MOD: feature dim updated (vector part changed + scalar_emb) =====
    def _cand_feat_dim(self) -> int:
        """
        Vector part (reduced redundancy):
          [s, mu_cur, delta] -> 3 * d

        Scalar embedding:
          scalar_mlp output -> hidden_dim//2

        Total = 3d + hidden_dim//2
        """
        return 2 * self.state_dim + (self.hidden_dim // 2)

    # ===== ★ MOD: ctx dim updated (optionally includes batch stats) =====
    def _ctx_feat_dim(self) -> int:
        """
        Context vector:
          [s, mu_cur] -> 2d
          ctx_scalars -> 8 (same as your original)
          + optional batch_stats -> 3 (move_ratio, noop_ratio, planned_out_frac) if provided
        We'll allocate for 8+3 = 11, but if batch_stats not provided we fill zeros.
        """
        # H_mean (hidden_dim) + batch_stats(3)
        return self.hidden_dim + 3

    @staticmethod
    def _safe_scalar(x: torch.Tensor, max_val: float) -> torch.Tensor:
        """
        Numerically safe scalar:
        - keep symmetry
        - avoid hard 0-clipping
        """
        x = torch.nan_to_num(
            x,
            nan=max_val,
            posinf=max_val,
            neginf=-max_val
        )
        x = torch.clamp(x, -max_val, max_val)
        return x

    def forward(
        self,
        s: torch.Tensor,
        mu_cur: torch.Tensor,
        cand_centers: torch.Tensor,
        cand_logsz: torch.Tensor,
        cand_comp: torch.Tensor,
        cand_dist: torch.Tensor,
        cur_logsz: torch.Tensor,
        cur_comp: torch.Tensor,
        cur_dist: torch.Tensor,
        kl_cur: torch.Tensor,
        kl_cand: torch.Tensor,
        batch_stats: torch.Tensor = None,   # ===== ★ NEW (optional, backward compatible)
        noop_mask: torch.Tensor = None,     # ===== ★ NEW (optional): explicit NOOP indicator [M]
    ):
        """
        Returns: logits [M], value scalar, entropy scalar

        batch_stats (optional): tensor [3] = [move_ratio, noop_ratio, planned_out_frac]
          - If not provided, auto-fill zeros.
        noop_mask (optional): [M] float/bool, 1 for NOOP candidate (cur cluster), else 0.
          - If not provided, we derive it by nearest match on cand_dist==cur_dist (fallback),
            but it's better to pass it from outside.
        """
        M = cand_centers.size(0)
        d = s.size(0)
        device = s.device

        # ---- sanitize scalars ----
        kl_cur = self._safe_scalar(kl_cur.view(1), self.max_kl)      # [1]
        kl_cand = self._safe_scalar(kl_cand.view(M), self.max_kl)    # [M]

        cand_dist = torch.nan_to_num(cand_dist, nan=1e6, posinf=1e6, neginf=1e6)
        cand_logsz = torch.nan_to_num(cand_logsz, nan=0.0)
        cand_comp = torch.nan_to_num(cand_comp, nan=1.0)

        cand_dist = torch.nan_to_num(cand_dist, nan=1e3, posinf=1e3)
        cur_dist = torch.nan_to_num(cur_dist.view(1), nan=1e3)
        cur_logsz = torch.nan_to_num(cur_logsz.view(1), nan=0.0)
        cur_comp = torch.nan_to_num(cur_comp.view(1), nan=1.0)

        # ---- vector parts ----
        s_rep = s.view(1, d).expand(M, d)
        mu_cur_rep = mu_cur.view(1, d).expand(M, d)
        mu_cand = cand_centers

        # ===== ★ MOD: keep delta, drop direct mu_cand concat later (less redundancy) =====
        delta = mu_cand - mu_cur_rep  # [M,d]

        # ===== ★ NEW: geometric similarity features =====
        cos_sc = F.cosine_similarity(mu_cand, mu_cur_rep, dim=1)  # [M]
        delta_norm = torch.norm(delta, dim=1)                     # [M]

        # ===== ★ NEW: explicit comparison features =====
        delta_kl = (kl_cand - kl_cur.view(1)).view(M)             # [M]
        delta_dist = (cand_dist - cur_dist.view(1)).view(M)       # [M]

        # ===== ★ NEW: explicit NOOP indicator =====
        if noop_mask is None:
            # Fallback heuristic: NOOP candidate usually has the same center as mu_cur,
            # but we don't have cand_idx here. Use cosine similarity + small delta norm.
            # This is only a fallback; passing noop_mask from outside is recommended.
            noop_mask = (delta_norm < 1e-8).float()
        else:
            noop_mask = noop_mask.float().view(M)

        # ---- scalar parts (vectorized, clean) ----
        cand_scalars = torch.stack(
            [cand_dist, cand_logsz, cand_comp, kl_cand], dim=1
        )  # [M,4]

        cand_scalars = torch.cat(
            [
                cand_scalars,
                cos_sc.view(M, 1),
                delta_norm.view(M, 1),
                delta_kl.view(M, 1),
                delta_dist.view(M, 1),
                noop_mask.view(M, 1),
            ],
            dim=1
        )  # [M,9]

        cur_scalars = torch.cat(
            [cur_dist, cur_logsz, cur_comp, kl_cur], dim=0
        ).view(1, 4).expand(M, 4)  # [M,4]

        scalars = torch.cat([cand_scalars, cur_scalars], dim=1)  # [M,13]

        # ===== ★ NEW: scalar embedding =====
        scalar_emb = self.scalar_mlp(scalars)  # [M, hidden_dim//2]

        # ===== ★ MOD: per-candidate feature (less redundancy) =====
        # Old: [s_rep, mu_cur_rep, mu_cand, delta, scalars]
        # New: [s_rep, mu_cur_rep, delta, scalar_emb]
        # X = torch.cat([s_rep, mu_cur_rep, delta, scalar_emb], dim=1)  # [M, 3d + h/2]
        # ===== ★ NEW: relative formulation (stronger inductive bias) =====
        rel_s = s_rep - mu_cur_rep  # [M,d]

        vec_part = torch.cat([rel_s, delta], dim=1)  # [M, 2d]

        # ===== ★ NEW: scalar gating =====
        gate = torch.sigmoid(self.gate_layer(scalar_emb))  # [M, 2d]
        vec_part = vec_part * gate

        X = torch.cat([vec_part, scalar_emb], dim=1)

        H = self.cand_mlp(X)
        # ===== ★ NEW: attention across candidates =====
        # attn_scores = self.attn_layer(H)  # [M,1]
        # attn_weights = torch.softmax(attn_scores, dim=0)  # across candidates
        #
        # H_global = (attn_weights * H).sum(dim=0, keepdim=True)  # [1,hidden]
        # H_enhanced = H + H_global  # broadcast
        # ===== ★ NEW: multi-head attention =====
        attn_scores = self.attn_layer(H)  # [M, num_heads]
        attn_weights = torch.softmax(attn_scores, dim=0)

        H_heads = []
        for i in range(self.num_heads):
            w = attn_weights[:, i:i + 1]  # [M,1]
            H_head = (w * H).sum(dim=0, keepdim=True)  # [1, hidden]
            H_heads.append(H_head)

        H_multi = torch.cat(H_heads, dim=1)  # [1, hidden*num_heads]
        H_global = self.attn_proj(H_multi)  # [1, hidden]

        H_enhanced = H + H_global

        logits = self.actor_head(H_enhanced).squeeze(-1)

        # ===== ★ NEW: temperature scaling =====
        # temp = self.temperature.clamp(min=0.1, max=10.0)
        temp = self.temperature.clamp(min=0.1, max=5.0)
        # temp = 1.5

        logits = logits / temp

        # ---- critic ----
        k = min(3, cand_dist.numel())

        ctx_scalars = torch.stack([
            cur_dist.squeeze(),
            cur_logsz.squeeze(),
            cur_comp.squeeze(),
            kl_cur.squeeze(),

            cand_dist.topk(k, largest=False).values.mean(),
            kl_cand.topk(k, largest=False).values.mean(),
            cand_comp.mean(),
            cand_logsz.mean(),
        ], dim=0)  # [8]

        # ===== ★ NEW: critic sees actor representation =====
        H_mean = H.mean(dim=0)  # [hidden_dim]

        if batch_stats is None:
            batch_stats = torch.zeros(3, device=device)
        else:
            batch_stats = batch_stats.view(3)

        ctx = torch.cat([H_mean, batch_stats], dim=0)
        value = self.critic_mlp(ctx).squeeze(-1)

        # ---- entropy (stable) ----
        logits_safe = torch.nan_to_num(logits, nan=-1e9, posinf=-1e9, neginf=-1e9)
        logits_safe = logits_safe - logits_safe.max()

        log_probs = F.log_softmax(logits_safe, dim=0)
        probs = log_probs.exp()
        entropy = -(probs * log_probs).sum()
        entropy = entropy / torch.log(torch.tensor(float(M), device=entropy.device))

        return logits, value, entropy
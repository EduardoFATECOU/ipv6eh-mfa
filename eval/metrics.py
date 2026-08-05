"""Metricas de avaliacao para autenticacao continua (Cap. 8).

- CVR (Correct Verification Rate) = TPR
- FPR (False Positive Rate)
- AUC, EER, limiar para FPR alvo (o QP4 exige TPR > 95% com FPR < 3%)
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def _scores_labels(scores, labels) -> tuple:
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    return scores, labels


def roc_auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    scores, labels = _scores_labels(scores, labels)
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    # P(s_pos > s_neg) com empates contando 0.5
    order = np.concatenate([np.ones(pos.size), np.zeros(neg.size)])
    all_scores = np.concatenate([pos, neg])
    idx = np.argsort(all_scores, kind="stable")
    order = order[idx]
    ranks = np.arange(1, all_scores.size + 1, dtype=np.float64)
    # corretivo para empates
    uniq = np.unique(all_scores)
    if uniq.size < all_scores.size:
        for u in uniq:
            m = all_scores[idx] == u
            if m.sum() > 1:
                ranks[m] = ranks[m].mean()
    pos_rank_sum = ranks[order == 1].sum()
    return float((pos_rank_sum - pos.size * (pos.size + 1) / 2) / (pos.size * neg.size))


def eer(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Equal Error Rate: valor de fpr (== fnr) no limiar de cruzamento."""
    scores, labels = _scores_labels(scores, labels)
    if scores.size == 0 or (labels == 1).sum() == 0 or (labels == 0).sum() == 0:
        return float("nan")
    thresholds = np.unique(scores)
    melhor_diff = np.inf
    melhor_fpr = float("nan")
    for t in thresholds:
        pred = (scores >= t).astype(np.int64)
        tp = ((pred == 1) & (labels == 1)).sum()
        fn = ((pred == 0) & (labels == 1)).sum()
        fp = ((pred == 1) & (labels == 0)).sum()
        tn = ((pred == 0) & (labels == 0)).sum()
        tpr = tp / (tp + fn) if (tp + fn) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        diff = abs(fpr - (1.0 - tpr))
        if diff < melhor_diff:
            melhor_diff = diff
            melhor_fpr = fpr
    return float(melhor_fpr)


def tpr_at_fpr(scores: Sequence[float], labels: Sequence[int], alvo: float = 0.03) -> float:
    """Maior TPR observado com FPR <= alvo (critico do QP4)."""
    scores, labels = _scores_labels(scores, labels)
    if scores.size == 0 or (labels == 1).sum() == 0 or (labels == 0).sum() == 0:
        return float("nan")
    thresholds = np.unique(scores)
    melhor = 0.0
    for t in thresholds:
        pred = (scores >= t).astype(np.int64)
        tp = ((pred == 1) & (labels == 1)).sum()
        fn = ((pred == 0) & (labels == 1)).sum()
        fp = ((pred == 1) & (labels == 0)).sum()
        tn = ((pred == 0) & (labels == 0)).sum()
        fpr = fp / (fp + tn) if (fp + tn) else 1.0
        if fpr <= alvo:
            tpr = tp / (tp + fn) if (tp + fn) else 0.0
            melhor = max(melhor, tpr)
    return float(melhor)


def resumo(scores: Sequence[float], labels: Sequence[int]) -> dict:
    """Pacote de metricas para uma execucao (usado nas Tabelas 8.x)."""
    return {
        "auc": roc_auc(scores, labels),
        "eer": eer(scores, labels),
        "tpr_fpr3": tpr_at_fpr(scores, labels, 0.03),
        "n_pos": int(np.asarray(labels).sum()),
        "n_neg": int(np.asarray(labels).size - np.asarray(labels).sum()),
    }

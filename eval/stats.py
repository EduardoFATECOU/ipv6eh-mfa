"""Estatistica nao-parametrica para comparacao de algoritmos (Cap. 8).

Implementacao em NumPy puro do teste de Friedman (com a correcao de
Iman-Davenport) e do post-hoc de Nemenyi (critical difference), usados nas
Tabelas 8.x para comparar FTRL, ARF, Ensemble e DQN sobre as repeticoes.

Referencias:
  Demšar (2006), 'Statistical Comparisons of Classifiers over Multiple
  Data Sets', JMLR 7(Jan):1-30.
  Friedman (1937); Iman & Davenport (1980).
"""

from __future__ import annotations

import numpy as np

#: Valores criticos q de Nemenyi (alpha=0.05) para k=2..10 algoritmos.
Q_ALPHA_05 = {
    2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728,
    6: 2.850, 7: 2.949, 8: 3.031, 9: 3.102, 10: 3.164,
}
#: Valores criticos q de Nemenyi (alpha=0.10) para k=2..10 algoritmos.
Q_ALPHA_10 = {
    2: 1.645, 3: 2.052, 4: 2.291, 5: 2.459,
    6: 2.589, 7: 2.693, 8: 2.780, 9: 2.855, 10: 2.920,
}
#: Valores criticos de chi-quadrado (alpha=0.05) para df=1..9.
CHI2_CRIT_05 = {
    1: 3.841, 2: 5.991, 3: 7.815, 4: 9.488, 5: 11.070,
    6: 12.592, 7: 14.067, 8: 15.507, 9: 16.919,
}


def _rankdata(valores: np.ndarray) -> np.ndarray:
    """Ranks com tratamento de empates (media dos ranks), como scipy.stats.rankdata."""
    a = np.asarray(valores)
    sorter = np.argsort(a, kind="mergesort")
    inv = np.empty(a.size, dtype=np.intp)
    inv[sorter] = np.arange(a.size)
    a_ordenado = a[sorter]
    obs = np.r_[True, a_ordenado[1:] != a_ordenado[:-1]]
    dense = obs.cumsum()[inv]
    contagem = np.r_[np.nonzero(obs)[0], len(obs)]
    return 0.5 * (contagem[dense] + contagem[dense - 1] + 1)


def media_ranks(dados: np.ndarray) -> np.ndarray:
    """Rank medio por algoritmo (linhas=algoritmos, colunas=repeticoes).

    Convencao de Demšar: rank 1 = melhor (maior valor). Valores sao
    negados antes da ordenacao ascendente.
    """
    dados = np.asarray(dados, dtype=np.float64)
    ranks = np.apply_along_axis(lambda col: _rankdata(-col), 0, dados)
    return ranks.mean(axis=1)


def friedman(dados: np.ndarray) -> dict:
    """Teste de Friedman: retorna chi2 (Friedman) e F (Iman-Davenport).

    ``dados`` deve ter shape (k, n) com k algoritmos e n repeticoes
    (maior valor = melhor). Inclui a comparacao com o valor critico
    chi2(alpha=0.05, k-1) para rejeicao da hipotese nula.
    """
    dados = np.asarray(dados, dtype=np.float64)
    k, n = dados.shape
    r = media_ranks(dados)
    chi2 = 12.0 * n / (k * (k + 1)) * (float(np.sum(r**2)) - k * (k + 1) ** 2 / 4.0)
    f = (n - 1.0) * chi2 / (n * (k - 1.0) - chi2) if n * (k - 1) > chi2 else float("inf")
    crit = CHI2_CRIT_05.get(k - 1)
    return {
        "k": k,
        "n": n,
        "chi2_friedman": float(chi2),
        "f_imandavenport": float(f),
        "gl": (k - 1, (k - 1) * (n - 1)),
        "chi2_crit_05": crit,
        "rejeita_nula_05": bool(crit is not None and chi2 > crit),
    }


def nemenyi_cd(k: int, n: int, alpha: float = 0.05) -> float:
    """Critical difference de Nemenyi: CD = q_alpha * sqrt(k(k+1)/(6n))."""
    tabela = Q_ALPHA_05 if alpha <= 0.05 else Q_ALPHA_10
    if k not in tabela:
        raise ValueError(f"tabela de Nemenyi so cobre k=2..10 (recebido k={k})")
    return float(tabela[k] * np.sqrt(k * (k + 1) / (6.0 * n)))


def pares_significativos(dados: np.ndarray, alpha: float = 0.05) -> list:
    """Pares de algoritmos cuja diferenca de rank medio excede o CD de Nemenyi."""
    dados = np.asarray(dados, dtype=np.float64)
    k, n = dados.shape
    r = media_ranks(dados)
    cd = nemenyi_cd(k, n, alpha)
    pares = [(i, j) for i in range(k) for j in range(i + 1, k) if abs(r[i] - r[j]) > cd]
    return [(int(i), int(j)) for i, j in pares]


def comparar(modelos: list, dados: np.ndarray, alpha: float = 0.05) -> dict:
    """Empacota a comparacao completa (ranks, Friedman, Nemenyi) para uma tabela."""
    dados = np.asarray(dados, dtype=np.float64)
    r = media_ranks(dados)
    pares = pares_significativos(dados, alpha)
    return {
        "modelos": list(modelos),
        "ranks": {m: float(r[i]) for i, m in enumerate(modelos)},
        "friedman": friedman(dados),
        "nemenyi_cd": nemenyi_cd(dados.shape[0], dados.shape[1], alpha),
        "pares_significativos": [(modelos[i], modelos[j]) for i, j in pares],
    }

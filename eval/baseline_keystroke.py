"""Baseline academico com o dataset CMU Keystroke (DSL-StrongPasswordData).

Protocolo de avaliacao (autenticacao continua por usuario):
  - 51 usuarios x 400 repeticoes da senha ".tie5Roanl" (31 features de timing);
  - para cada usuario: treino com 200 repeticoes genuinas (classe 1) +
    200 repeticoes de impostores (classe 0) e teste com as 200 restantes
    genuinas + 200 impostoras;
  - modelos online: FTRL-Proximal e ARF (River), avaliados por EER, AUC
    e TPR com FPR <= 3% (criterio do QP4).

Fonte: Killourhy & Maxion (2009), CMU 'DSL-StrongPasswordData'.
Licenca: uso academico, disponivel em http://www.cs.cmu.edu/~keystroke/
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.metrics import resumo  # noqa: E402
from ml.models import ARFModel, FTRLModel, featurize  # noqa: E402

DATA = ROOT / "data" / "DSL-StrongPasswordData.csv"
RESULTADOS = ROOT / "eval" / "results"


def carregar() -> tuple:
    """Carrega o CSV e separa (subjects, features) sem pandas."""
    subjects = []
    features = []
    with open(DATA, newline="") as fh:
        leitor = csv.DictReader(fh)
        for linha in leitor:
            subjects.append(linha["subject"])
            features.append([float(linha[k]) for k in linha if k not in ("subject", "sessionIndex", "rep")])
    return np.asarray(subjects), np.asarray(features, dtype=np.float64)


def construir_modelo(nome: str, seed: int):
    if nome == "ftrl":
        return FTRLModel(alpha=0.05, beta=1.0)
    if nome == "arf":
        return ARFModel(n_models=10, max_depth=10, lambda_value=10)
    raise ValueError(nome)


def avaliar_usuario(usuarios: np.ndarray, x: np.ndarray, alvo: str, nome: str, seed: int) -> dict:
    idx = np.where(usuarios == alvo)[0]
    impostores = np.where(usuarios != alvo)[0]
    rng = np.random.default_rng(seed)
    sel_imp = rng.choice(impostores, size=idx.size, replace=False)

    x_pos = x[idx]
    x_neg = x[sel_imp]
    pos_tr, pos_te = x_pos[:200], x_pos[200:]
    neg_tr, neg_te = x_neg[:200], x_neg[200:]

    modelo = construir_modelo(nome, seed)
    for i in range(200):
        modelo.learn_one(featurize(pos_tr[i]), 1)
        modelo.learn_one(featurize(neg_tr[i]), 0)

    scores, labels = [], []
    for i in range(pos_te.shape[0]):
        scores.append(modelo.predict_proba_one(featurize(pos_te[i])).get(1, 0.5))
        labels.append(1)
    for i in range(neg_te.shape[0]):
        scores.append(modelo.predict_proba_one(featurize(neg_te[i])).get(1, 0.5))
        labels.append(0)
    return resumo(scores, labels)


def executar(modelo: str, seed: int = 42) -> list:
    usuarios, x = carregar()
    linhas = []
    for alvo in sorted(set(usuarios)):
        m = avaliar_usuario(usuarios, x, alvo, modelo, seed)
        linhas.append({"usuario": alvo, **{k: round(v, 4) for k, v in m.items()}})
    return linhas


def main() -> None:
    RESULTADOS.mkdir(exist_ok=True)
    for modelo in ("ftrl", "arf"):
        linhas = executar(modelo)
        saida = RESULTADOS / f"keystroke_{modelo}.csv"
        with open(saida, "w", newline="", encoding="utf-8") as fh:
            campo = ["usuario", "auc", "eer", "tpr_fpr3", "n_pos", "n_neg"]
            esc = csv.DictWriter(fh, fieldnames=campo)
            esc.writeheader()
            esc.writerows(linhas)
        aucs = [l["auc"] for l in linhas]
        eers = [l["eer"] for l in linhas]
        tprs = [l["tpr_fpr3"] for l in linhas]
        print(f"== CMU Keystroke - {modelo.upper()} ==")
        print(f"  AUC:  media={np.mean(aucs):.4f} +- {np.std(aucs):.4f}")
        print(f"  EER:  media={np.mean(eers):.4f} +- {np.std(eers):.4f}")
        print(f"  TPR@FPR<=3%: media={np.mean(tprs):.4f} +- {np.std(tprs):.4f}")
        print(f"  -> {saida}\n")


if __name__ == "__main__":
    main()

"""Teste de robustez do cenario C1 (Roubo de Credenciais).

Motivacao (roteiro_tese.md, Secao 5): a AUC ~ 1.0 do C1 pode ser vista pela
banca como "separabilidade facil" dos ataques sinteticos. Este script injeta
camuflagem no atacante: cada evento C1 e misturado com um evento legitimo
(twin) via blend convexo

    X_pert(eps) = (1 - eps) * X_C1 + eps * X_legitimo_twin,

em que eps (nivel de perturbacao) varia em {0.0, 0.2, 0.4, 0.6, 0.8, 1.0}.
O blend vale para todas as features (continuas e one-hot, que permanecem
vetores de probabilidade validos). eps=0 reproduz o C1 original; eps = 1.0
torna o atacante indistinguivel do legitimo (controle: AUC -> 0.5).

Objetivo: demonstrar degradacao graciosa -- a deteccao nao e trivial, e a
AUC alta do C1 decorre do sinal legitimo, nao de um artefato do fluxo.

Uso:
    python -m eval.robustez_c1 --reps 10 --eventos 12000 --warm 1000

Saidas em eval/results/:
    robustez_c1.csv   (uma linha por repeticao x eps x modelo x cenario)
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.simulador import (  # noqa: E402
    _estatisticas,
    _metricas_por_cenario,
    _padronizar,
    avaliar_detector,
    carregar_classes,
    montar_stream,
)

RESULTADOS = ROOT / "eval" / "results"

NIVEIS_PADRAO = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def perturbar_c1(classes: dict, epsilon: float, seed: int) -> dict:
    """Classes com o C1 camuflado: blend convexo de cada ataque C1 com um
    evento legitimo (twin) sorteado deterministicamente."""
    c1 = classes[1]
    leg = classes[0]
    rng = np.random.RandomState(seed)
    idx = rng.randint(0, len(leg), size=len(c1))
    c1_pert = (1.0 - epsilon) * c1 + epsilon * leg[idx]
    out = dict(classes)
    out[1] = c1_pert
    return out


def executar(reps: int, n_total: int, warm: int, modelos: list, niveis: tuple,
             seed_base: int, resultados: Path = RESULTADOS) -> list:
    classes = carregar_classes()
    linhas = []
    for rep in range(reps):
        for eps in niveis:
            classes_pert = perturbar_c1(classes, eps, seed_base + rep)
            X, y = montar_stream(classes_pert, n_total, warm, seed_base + rep)
            med, des = _estatisticas(X, warm)
            X = _padronizar(X, med, des)
            for nome in modelos:
                det = avaliar_detector(X, y, nome, warm, seed_base + rep)
                por_cenario = _metricas_por_cenario(det["scores"], det["ybin"], det["cenario"])
                for cenario, m in por_cenario.items():
                    linhas.append({
                        "rep": rep, "epsilon": eps, "modelo": nome, "cenario": cenario,
                        "auc": round(m["auc"], 4), "eer": round(m["eer"], 4),
                        "tpr_fpr3": round(m["tpr_fpr3"], 4), "tpr": round(m["tpr"], 4),
                        "fpr": round(m["fpr"], 4), "precisao": round(m["precisao"], 4),
                        "recall": round(m["recall"], 4), "f1": round(m["f1"], 4),
                        "n_pos": m["n_pos"], "n_neg": m["n_neg"],
                        "drift": det["drift"],
                    })
    _escrever_csv(resultados / "robustez_c1.csv",
                  ["rep", "epsilon", "modelo", "cenario", "auc", "eer", "tpr_fpr3",
                   "tpr", "fpr", "precisao", "recall", "f1", "n_pos", "n_neg", "drift"],
                  linhas)
    return linhas


def _escrever_csv(caminho: Path, campo: list, linhas: list) -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        esc = csv.DictWriter(fh, fieldnames=campo, extrasaction="ignore")
        esc.writeheader()
        esc.writerows(linhas)


def _media_std(linhas: list, eps: float, modelo: str, campo: str) -> tuple:
    v = [float(l[campo]) for l in linhas
         if l["epsilon"] == eps and l["modelo"] == modelo and l["cenario"] == "C1"
         and not np.isnan(float(l[campo]))]
    if not v:
        return float("nan"), float("nan")
    return float(np.mean(v)), float(np.std(v))


def resumir(linhas: list, modelos: list) -> str:
    out = ["# Robustez do C1 (camuflagem do atacante)\n",
           "| eps | Modelo | AUC | TPR@FPR<=3% | Precisao | F1 |",
           "|---:|---:|---:|---:|---:|---:|"]
    for eps in NIVEIS_PADRAO:
        for nome in modelos:
            auc, _ = _media_std(linhas, eps, nome, "auc")
            tpr, _ = _media_std(linhas, eps, nome, "tpr_fpr3")
            prec, _ = _media_std(linhas, eps, nome, "precisao")
            f1, _ = _media_std(linhas, eps, nome, "f1")
            out.append(f"| {eps:.1f} | {nome.upper()} | {auc:.4f} | {tpr:.4f} | "
                       f"{prec:.4f} | {f1:.4f} |")
    return "\n".join(out)


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--eventos", type=int, default=12000)
    ap.add_argument("--warm", type=int, default=1000)
    ap.add_argument("--modelos", default="ftrl,ensemble")
    ap.add_argument("--niveis", default="0,0.2,0.4,0.6,0.8,1.0")
    ap.add_argument("--seed-base", type=int, default=42)
    args = ap.parse_args(argv)

    modelos = [m.strip() for m in args.modelos.split(",") if m.strip()]
    niveis = tuple(float(v) for v in args.niveis.split(","))
    RESULTADOS.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    linhas = executar(args.reps, args.eventos, args.warm, modelos, niveis, args.seed_base)
    resumo_md = resumir(linhas, modelos)
    (RESULTADOS / "robustez_c1.md").write_text(resumo_md, encoding="utf-8")

    print(resumo_md)
    print(f"\nRobustez concluida em {time.time() - t0:.1f}s.")
    print(f"-> {RESULTADOS / 'robustez_c1.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

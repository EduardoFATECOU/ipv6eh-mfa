"""Executa todos os baselines academicos e gera o resumo consolidado."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTADOS = ROOT / "eval" / "results"


def _media_std(arquivo: Path, campo: str) -> tuple:
    import csv

    valores = []
    with open(arquivo, newline="", encoding="utf-8") as fh:
        for linha in csv.DictReader(fh):
            v = float(linha[campo])
            if not np.isnan(v):
                valores.append(v)
    if not valores:
        return float("nan"), float("nan")
    return float(np.mean(valores)), float(np.std(valores))


def resumir() -> str:
    import csv

    linhas = []
    for dataset in ("keystroke", "balabit"):
        for modelo in ("ftrl", "arf"):
            arq = RESULTADOS / f"{dataset}_{modelo}.csv"
            if not arq.exists():
                continue
            with open(arq, newline="", encoding="utf-8") as fh:
                n = sum(1 for _ in csv.DictReader(fh))
            auc_m, auc_s = _media_std(arq, "auc")
            eer_m, eer_s = _media_std(arq, "eer")
            tpr_m, tpr_s = _media_std(arq, "tpr_fpr3")
            linhas.append(
                f"| {dataset} | {modelo.upper()} | {n} | "
                f"{auc_m:.4f} ± {auc_s:.4f} | {eer_m:.4f} ± {eer_s:.4f} | "
                f"{tpr_m:.4f} ± {tpr_s:.4f} |"
            )
    cab = (
        "| Dataset | Modelo | Usuarios | AUC | EER | TPR@FPR<=3% |\n"
        "|---|---|---:|---|---|---|"
    )
    return "## Baselines academicos (dados publicos)\n\n" + cab + "\n" + "\n".join(linhas) + "\n"


def main() -> None:
    from eval.baseline_balabit import main as balabit
    from eval.baseline_keystroke import main as keystroke

    print("### CMU Keystroke")
    keystroke()
    print("### Balabit Mouse Dynamics")
    balabit()
    resumo = resumir()
    (RESULTADOS / "RESUMO.md").write_text(resumo, encoding="utf-8")
    print("\n" + resumo)
    print(f"\n-> {RESULTADOS / 'RESUMO.md'}")


if __name__ == "__main__":
    main()

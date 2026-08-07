"""Baseline MFA estatica (OE6/QP4): senha + TOTP a cada 30 min.

A MFA estatica autentica apenas no inicio da sessao (e a cada 30 min, via
TOTP) e NAO realiza verificacao continua por evento. Sobre o fluxo temporal
da campanha C1-C4 (montar_stream), um atacante que opera dentro de uma
sessao ja autenticada -- com credenciais roubadas (C1), em MITM (C2),
replay de autenticacao (C3) ou spoofing de agente (C4) -- nao e observado
pela MFA estatica: nao ha sinal comportamental por pacote.

Portanto, a politica estatica nunca dispara resposta de seguranca:

    TPR = 0  (nenhum ataque no meio da sessao e detectado)
    FPR = 0  (nunca bloqueia/escalona um legitimante)

Este script materializa essa politica sobre o mesmo stream da campanha
(repeticao x cenario), gravando `eval/results/baseline_estatica.csv` para
a tabela de comparacao do Cap. 8 (OE6).

Uso:
    python -m eval.baseline_mfa_estatica
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.simulador import _estatisticas, _padronizar, carregar_classes, montar_stream  # noqa: E402

RESULTADOS = ROOT / "eval" / "results"
DESTINO = ROOT / "data" / "ipv6eh"


def executar(reps: int, n_total: int, warm: int, seed_base: int,
             destino: Path = DESTINO, resultados: Path = RESULTADOS) -> list:
    """Simula a politica estatica (sem sinal por evento) sobre o stream."""
    classes = carregar_classes(destino)
    linhas = []
    for rep in range(reps):
        seed = seed_base + rep
        X, y = montar_stream(classes, n_total, warm, seed)
        med, des = _estatisticas(X, warm)
        X = _padronizar(X, med, des)
        y_ev = y[warm:]
        cen = y_ev
        leg = y_ev == 0
        for c in (1, 2, 3, 4):
            ata = cen == c
            n_atk = int(ata.sum())
            n_leg = int(leg.sum())
            linhas.append({
                "rep": rep, "modelo": "mfa_estatica", "cenario": f"C{c}",
                "tpr": 0.0, "fpr": 0.0, "precisao": 0.0, "recall": 0.0, "f1": 0.0,
                "auc": float("nan"), "tpr_fpr3": 0.0,
                "tpr_pol": 0.0, "fpr_pol": 0.0,
                "taxa_bloqueio": 0.0, "taxa_escalada": 0.0,
                "n_atk": n_atk, "n_leg": n_leg,
            })
        linhas.append({
            "rep": rep, "modelo": "mfa_estatica", "cenario": "GLOBAL",
            "tpr": 0.0, "fpr": 0.0, "precisao": 0.0, "recall": 0.0, "f1": 0.0,
            "auc": float("nan"), "tpr_fpr3": 0.0,
            "tpr_pol": 0.0, "fpr_pol": 0.0,
            "taxa_bloqueio": 0.0, "taxa_escalada": 0.0,
            "n_atk": int((y_ev != 0).sum()), "n_leg": int(leg.sum()),
        })
    return linhas


def main() -> None:
    RESULTADOS.mkdir(exist_ok=True)
    linhas = executar(reps=5, n_total=20000, warm=2000, seed_base=42)
    saida = RESULTADOS / "baseline_estatica.csv"
    campo = ["rep", "modelo", "cenario", "tpr", "fpr", "precisao", "recall", "f1",
             "auc", "tpr_fpr3", "tpr_pol", "fpr_pol", "taxa_bloqueio", "taxa_escalada",
             "n_atk", "n_leg"]
    with open(saida, "w", newline="", encoding="utf-8") as fh:
        esc = csv.DictWriter(fh, fieldnames=campo, extrasaction="ignore")
        esc.writeheader()
        esc.writerows(linhas)
    print(f"MFA estatica (senha+TOTP 30 min): TPR=0, FPR=0 (sem verificacao continua)")
    print(f"-> {saida}")


if __name__ == "__main__":
    main()

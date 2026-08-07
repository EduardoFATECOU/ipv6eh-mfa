"""Gera as tabelas LaTeX do Cap. 8 a partir dos resultados da simulacao.

Le ``eval/results/simulacao_det.csv`` e ``simulacao_dqn.csv`` e emite, em
``eval/results/tabelas_cap8.tex``, as tabelas prontas para o abnTeX2:

  - Tabelas 8.1-8.4: TPR/FPR/Precisao/Recall/F1/AUC por cenario (media +- DP
    sobre as repeticoes), no ponto de operacao do QP4 (FPR <= 3%);
  - Tabela GLOBAL: mesmas metricas para todos os cenarios agregados;
  - Tabela 8.5: politica do Agente Decisor (DQN) - TPR/FPR e taxas de bloqueio/escalada;
  - Tabela 8.6: Friedman - ranking medio, estatistica Q e p-valor;
  - Tabela 8.7: Nemenyi - pares, diferenca de ranks, CD e significancia.
  - Tabela agregada por dimensao: Metrica | Cenario | Algoritmo | Media | DP | IC95.

Uso (apos rodar a campanha):
    python -m eval.gerar_tabelas [--saida eval/results] [--campo auc]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.stats import comparar  # noqa: E402

RESULTADOS = ROOT / "eval" / "results"

NOM = {"ftrl": "FTRL", "arf": "ARF", "ensemble": "Ensemble", "dqn": "DQN"}
CENARIOS = [("C1", "Roubo de Credenciais"), ("C2", "Man-in-the-Middle"),
            ("C3", "Replay de Autenticacao"), ("C4", "Spoofing de Agente")]


def _ler(caminho: Path) -> list:
    if not caminho.exists():
        raise FileNotFoundError(f"{caminho} nao existe. Rode a campanha antes.")
    with open(caminho, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _ms(rows: list, cenario: str, modelo: str, campo: str, eps: float = None) -> str:
    """Media +- DP (4 casas) de um campo por (cenario, modelo); com filtro eps."""
    v = [float(l[campo]) for l in rows
         if l["cenario"] == cenario and l["modelo"] == modelo
         and l.get(campo) not in ("", "nan")
         and (eps is None or float(l.get("epsilon", float("nan"))) == eps)]
    if not v:
        return "--"
    m, s = float(np.mean(v)), float(np.std(v))
    return f"{m:.4f} $\\pm$ {s:.4f}"


def _tabela_detectores(rows: list, modelos: list, cenario: str) -> str:
    out = ("\\begin{tabular}{l" + "r" * 6 + "}\n\\toprule\n"
           "Algoritmo & TPR & FPR & Precis\\~ao & Recall & F1 & AUC \\\\\n\\midrule\n")
    for modelo in modelos:
        out += (f"{NOM.get(modelo, modelo)} & {_ms(rows, cenario, modelo, 'tpr')} & "
                f"{_ms(rows, cenario, modelo, 'fpr')} & "
                f"{_ms(rows, cenario, modelo, 'precisao')} & "
                f"{_ms(rows, cenario, modelo, 'recall')} & "
                f"{_ms(rows, cenario, modelo, 'f1')} & "
                f"{_ms(rows, cenario, modelo, 'auc')} \\\\\n")
    return out + "\\bottomrule\n\\end{tabular}\n"


def _tabela_agregada(rows: list, modelos: list) -> str:
    out = ("\\begin{tabular}{lllrrr}\n\\toprule\n"
           "M\\'etrica & Cen\\'ario & Algoritmo & M\\'edia & DP & IC95\\% \\\\\n\\midrule\n")
    for campo in ("tpr", "fpr", "auc", "f1"):
        for cenario, _rot in CENARIOS:
            for modelo in modelos:
                v = [float(l[campo]) for l in rows
                     if l["cenario"] == cenario and l["modelo"] == modelo
                     and l.get(campo) not in ("", "nan")]
                if not v:
                    continue
                m, s = float(np.mean(v)), float(np.std(v))
                ic = 1.96 * s / np.sqrt(len(v))
                out += (f"{campo.upper()} & {cenario} & {NOM.get(modelo, modelo)} & "
                        f"{m:.4f} & {s:.4f} & $\\pm {ic:.4f}$ \\\\\n")
    return out + "\\bottomrule\n\\end{tabular}\n"


def _tabela_politica(dqn_rows: list) -> str:
    out = ("\\begin{tabular}{l" + "r" * 6 + "}\n\\toprule\n"
           "Cen\\'ario & TPR & FPR & Precis\\~ao & F1 & Bloqueio & Escalada \\\\\n\\midrule\n")
    for cenario in ("C1", "C2", "C3", "C4", "GLOBAL"):
        out += (f"{cenario} & {_ms(dqn_rows, cenario, 'dqn', 'tpr')} & "
                f"{_ms(dqn_rows, cenario, 'dqn', 'fpr')} & "
                f"{_ms(dqn_rows, cenario, 'dqn', 'precisao')} & "
                f"{_ms(dqn_rows, cenario, 'dqn', 'f1')} & "
                f"{_ms(dqn_rows, cenario, 'dqn', 'taxa_bloqueio')} & "
                f"{_ms(dqn_rows, cenario, 'dqn', 'taxa_escalada')} \\\\\n")
    return out + "\\bottomrule\n\\end{tabular}\n"


def _tabela_robustez(rob_rows: list) -> str:
    """Teste de robustez do C1: AUC/TPR@FPR<=3% por nivel de camuflagem (eps)."""
    out = ("\\begin{tabular}{rrrrr}\n\\toprule\n"
           "\\varepsilon & Modelo & AUC & TPR@FPR$\\le 3\\%$ & Precis\\~ao \\\\\n\\midrule\n")
    eps_ord = sorted({float(l["epsilon"]) for l in rob_rows})
    modelos = ("ftrl", "ensemble")
    for eps in eps_ord:
        for nome in modelos:
            out += (f"{eps:.1f} & {NOM.get(nome, nome)} & "
                    f"{_ms(rob_rows, 'C1', nome, 'auc', eps)} & "
                    f"{_ms(rob_rows, 'C1', nome, 'tpr_fpr3', eps)} & "
                    f"{_ms(rob_rows, 'C1', nome, 'precisao', eps)} \\\\\n")
    return out + "\\bottomrule\n\\end{tabular}\n"


def _tabela_baseline(rows: list, dqn_rows: list, baseline: list) -> str:
    """Comparacao com baselines do OE6/QP4: proposta vs. MFA estatica e
    Wang et al. (2023). Valores globais (todos os cenarios, 30 repeticoes)."""
    out = ("\\begin{tabular}{l" + "r" * 4 + "ll}\n\\toprule\n"
           "Sistema & TPR & FPR & Precis\\~ao & AUC & Observa\\c c\\~ao \\\\\n\\midrule\n")
    g = "GLOBAL"
    for nome in ("ensemble", "ftrl"):
        out += (f"Proposta --- {NOM.get(nome, nome)} & "
                f"{_ms(rows, g, nome, 'tpr')} & {_ms(rows, g, nome, 'fpr')} & "
                f"{_ms(rows, g, nome, 'precisao')} & {_ms(rows, g, nome, 'auc')} & "
                f"detec\\c c\\~ao cont\\'inua por evento (30 reps) \\\\\n")
    out += (f"Proposta --- DQN (calibrado) & "
            f"{_ms(dqn_rows, g, 'dqn', 'tpr')} & {_ms(dqn_rows, g, 'dqn', 'fpr')} & "
            f"{_ms(dqn_rows, g, 'dqn', 'precisao')} & {_ms(dqn_rows, g, 'dqn', 'auc')} & "
            f"pol\\'itica do Agente Decisor (ponto de opera\\c c\\~ao) \\\\\n")
    out += (f"MFA est\\'atica (senha+TOTP 30 min) & "
            f"{_ms(baseline, g, 'mfa_estatica', 'tpr')} & "
            f"{_ms(baseline, g, 'mfa_estatica', 'fpr')} & "
            f"-- & -- & sem verifica\\c c\\~ao cont\\'inua; TPR=0 no meio da sess\\~ao \\\\\n")
    out += ("Wang et al. (2023) & n/d & 0.021 & 0.967 & n/d & "
            "MFA adaptativa DL (12 features contextuais); "
            "m\\'etricas reportadas no dataset deles \\\\\n")
    return out + "\\bottomrule\n\\end{tabular}\n"


def _tabela_friedman(rows: list, modelos: list, cenario: str, campo: str) -> str:
    matriz = np.array([[float(l[campo]) for l in rows
                        if l["cenario"] == cenario and l["modelo"] == m]
                       for m in modelos], dtype=np.float64)
    comp = comparar(modelos, matriz)
    f = comp["friedman"]
    p = f["p_chi2"]
    p_str = f"{p:.4f}" if p is not None else "--"
    ranks = " / ".join(f"{NOM.get(m, m)}={comp['ranks'][m]:.3f}" for m in modelos)
    return (f"{cenario} & $Q={f['chi2_friedman']:.3f}$, $p={p_str}$, "
            f"$F={f['f_imandavenport']:.3f}$ \\\\\n  & $ranking$: {ranks} \\\\\n")


def _tabela_nemenyi(rows: list, modelos: list, cenario: str, campo: str) -> str:
    matriz = np.array([[float(l[campo]) for l in rows
                        if l["cenario"] == cenario and l["modelo"] == m]
                       for m in modelos], dtype=np.float64)
    comp = comparar(modelos, matriz)
    cd = comp["nemenyi_cd"]
    pares = comp["pares_significativos"]
    out = ("\\begin{tabular}{llrrc}\n\\toprule\n"
           "Fonte & Alvo & $\\Delta$Ranks & CD & Significativo \\\\\n\\midrule\n")
    k = len(modelos)
    for i in range(k):
        for j in range(i + 1, k):
            dr = abs(comp["ranks"][modelos[i]] - comp["ranks"][modelos[j]])
            sig = "sim" if (modelos[i], modelos[j]) in pares else "n\\~ao"
            out += (f"{NOM.get(modelos[i], modelos[i])} & "
                    f"{NOM.get(modelos[j], modelos[j])} & {dr:.3f} & {cd:.3f} & {sig} \\\\\n")
    return out + "\\bottomrule\n\\end{tabular}\n"


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saida", default=str(RESULTADOS))
    ap.add_argument("--campo", default="auc", help="campo do teste estatistico")
    args = ap.parse_args(argv)
    saida = Path(args.saida)
    rows = _ler(saida / "simulacao_det.csv")
    dqn = _ler(saida / "simulacao_dqn.csv")
    baseline = _ler(saida / "baseline_estatica.csv")
    robust = _ler(saida / "robustez_c1.csv")
    modelos = sorted({l["modelo"] for l in rows if l["modelo"] != "dqn"})
    n_rep = max(int(l["rep"]) for l in rows) + 1

    partes = ["% Tabelas do Cap. 8 geradas por eval/gerar_tabelas.py",
              f"% {n_rep} repeticoes; ponto de operacao TPR@FPR<=3\\% (QP4).", ""]

    for idx, (cenario, rotulo) in enumerate(CENARIOS, start=1):
        partes.append(
            f"\\begin{{table}}[htbp]\n\\centering\n"
            f"\\caption{{{rotulo} ({cenario}) — detectores no ponto de operação do QP4 "
            f"(FPR$\\le 3\\%$, média $\\pm$ desvio padrão sobre {n_rep} repetições).}}\n"
            f"\\label{{tab:8-{idx}}}\n"
            + _tabela_detectores(rows, modelos, cenario)
            + "\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  "\\caption{GLOBAL — detectores no ponto de operação do QP4, todos os cenários.}\n"
                  "\\label{tab:8-global}\n"
                  + _tabela_detectores(rows, modelos, "GLOBAL")
                  + "\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  "\\caption{Comparação com baselines (OE6/QP4) — proposta versus MFA estática "
                  "e Wang et al. (2023), agregado sobre todos os cenários.}\n"
                  "\\label{tab:8-baseline}\n"
                  + _tabela_baseline(rows, dqn, baseline)
                  + "\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  "\\caption{Robustez do cenário C1 — camuflagem do atacante (blend convexo "
                  "com comportamento legítimo, nível $\\varepsilon$). AUC $\\to 0.5$ quando o "
                  "ataque se torna indistinguível (controle em $\\varepsilon=1.0$).}\n"
                  "\\label{tab:8-robustez}\n"
                  + _tabela_robustez(robust)
                  + "\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  f"\\caption{{Política do Agente Decisor (DQN) — ponto de operação calibrado "
                  f"(FPR$\\le 3\\%$) sobre o score $Q(bloquear)-Q(permitir)$, "
                  f"{n_rep} repetições. Bloqueio/Escalada referem-se à política greedy reportada.}}\n"
                  f"\\label{{tab:8-5}}\n"
                  + _tabela_politica(dqn)
                  + "\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  "\\caption{Friedman — estatística Q, p-valor e ranking médio (Demšar) "
                  "sobre a AUC.}\n\\label{tab:8-6}\n"
                  "\\begin{tabular}{ll}\n\\toprule\nCenário & Resultado \\\\\n\\midrule\n")
    for cenario, _rot in CENARIOS:
        partes.append(_tabela_friedman(rows, modelos, cenario, args.campo))
    partes.append("\\bottomrule\n\\end{tabular}\n\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  "\\caption{Nemenyi — pares com diferença de ranks significativa (acima do CD).}\n"
                  "\\label{tab:8-7}\n"
                  + _tabela_nemenyi(rows, modelos, "GLOBAL", args.campo)
                  + "\\end{table}\n")

    partes.append("\\begin{table}[htbp]\n\\centering\n"
                  "\\caption{Resultados agregados por dimensão de métrica.}\n"
                  "\\label{tab:8-agreg}\n"
                  + _tabela_agregada(rows, modelos)
                  + "\\end{table}\n")

    tex = "\n".join(partes)
    (saida / "tabelas_cap8.tex").write_text(tex, encoding="utf-8")
    print(f"-> {saida / 'tabelas_cap8.tex'} ({len(tex)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
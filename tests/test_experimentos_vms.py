"""Testes do runner de experimentos (eval/experimentos_vms.py)."""

import csv
import json

import numpy as np
import pytest

from eval.experimentos_vms import (
    COLUNAS,
    escrever_csv,
    executar_coleta,
    ler_auditoria,
    ler_rotulos,
    main,
    metricas_cenario,
    normalizar_rotulo,
)


def _ler_csv(caminho):
    with open(caminho, newline="", encoding="utf-8") as fh:
        leitor = csv.DictReader(fh)
        return leitor.fieldnames, list(leitor)


def test_metricas_cenario_separa_ataque_e_legitimo():
    scores = np.array([0.9, 0.8, 0.2, 0.1, 0.95])
    ybin = np.array([1, 1, 0, 0, 1])
    cen = np.array([1, 1, 0, 0, 2])
    m = metricas_cenario(scores, ybin, cen, 1)
    assert m["n_pos"] == 2 and m["n_neg"] == 2
    assert m["tpr"] == 1.0 and m["fpr"] == 0.0
    assert m["auc"] == 1.0


def test_metricas_cenario_sem_eventos_falha():
    with pytest.raises(ValueError, match="sem eventos"):
        metricas_cenario([0.5, 0.4], [0, 0], [0, 0], 1)


def test_normalizar_rotulo():
    assert normalizar_rotulo("legitimo") == 0
    assert normalizar_rotulo(0) == 0
    assert normalizar_rotulo("C1") == 1
    assert normalizar_rotulo("c4") == 4
    assert normalizar_rotulo("3") == 3


def test_escrever_csv_colunas_e_nan_vazio(tmp_path):
    linhas = [{
        "cenario": "C1", "rep": 0, "seed": 42, "fonte": "simulado",
        "modelo": "ensemble", "eventos": 10, "tpr": 0.9, "fpr": 0.01,
        "auc": 0.95, "eer": 0.05, "tpr_fpr3": 0.9, "precisao": 0.9,
        "recall": 0.9, "f1": 0.9, "lat_p50_ms": 0.01, "lat_p95_ms": 0.02,
        "lat_p99_ms": 0.03, "cpu_pct": float("nan"), "rss_mb": 100.0,
        "bloqueios": 3, "escaladas": 1, "duracao_s": 1.5,
    }]
    caminho = escrever_csv(tmp_path / "x.csv", linhas)
    campos, lidos = _ler_csv(caminho)
    assert campos == COLUNAS
    assert lidos[0]["cpu_pct"] == ""
    assert lidos[0]["bloqueios"] == "3"


def _gerar_dataset(destino):
    """Dataset sintetico pequeno com as colunas exigidas por carregar_classes."""
    destino.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    dias = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
    disp = ("laptop", "smartphone", "tablet", "desktop", "servidor")
    cabecalho = (["hora_dia", "hist_autent", "taxa_erro", "pacotes_s", "flow_label",
                  "confianca_fator"]
                 + [f"dia_{d}" for d in dias] + [f"disp_{d}" for d in disp]
                 + ["localizacao"])
    for codigo, nome in enumerate(("legitimo", "c1", "c2", "c3", "c4")):
        centro = 0.0 if codigo == 0 else float(codigo) + 1.0
        with open(destino / f"{nome}.csv", "w", newline="", encoding="utf-8") as fh:
            escritor = csv.DictWriter(fh, fieldnames=cabecalho)
            escritor.writeheader()
            for _ in range(2000):
                linha = {
                    "hora_dia": round(float(rng.uniform(0, 24)), 2),
                    "hist_autent": int(rng.integers(1, 12)),
                    "taxa_erro": round(abs(float(rng.normal(centro, 0.5))), 2),
                    "pacotes_s": round(abs(float(rng.normal(200 * centro + 100, 20))), 1),
                    "flow_label": float(rng.integers(0, 2)),
                    "confianca_fator": round(min(1.0, max(0.0, 1.0 - centro / 6.0
                                                       + float(rng.normal(0, 0.05)))), 4),
                    "localizacao": "9q8yy",
                }
                for j, d in enumerate(dias):
                    linha[f"dia_{d}"] = int(j == int(rng.integers(0, 7)))
                for j, d in enumerate(disp):
                    linha[f"disp_{d}"] = int(j == int(rng.integers(0, 5)))
                escritor.writerow(linha)
    return destino


def test_simulado_uma_repeticao_gera_csv(tmp_path):
    dados = _gerar_dataset(tmp_path / "data")
    codigo = main([
        "--cenario", "C1", "--reps", "1", "--seed", "42",
        "--eventos", "2500", "--warm", "250", "--modelos", "ensemble",
        "--destino", str(dados), "--saida", str(tmp_path), "--silencioso",
    ])
    assert codigo == 0
    campos, linhas = _ler_csv(tmp_path / "experimentos.csv")
    assert campos == COLUNAS
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["cenario"] == "C1"
    assert linha["fonte"] == "simulado"
    assert linha["modelo"] == "ensemble"
    assert int(linha["eventos"]) > 0
    assert 0.0 <= float(linha["tpr"]) <= 1.0
    assert 0.0 <= float(linha["fpr"]) <= 1.0
    assert 0.0 <= float(linha["auc"]) <= 1.0


def test_simulado_all_gera_quatro_cenarios(tmp_path):
    dados = _gerar_dataset(tmp_path / "data")
    codigo = main([
        "--cenario", "ALL", "--reps", "1", "--seed", "7",
        "--eventos", "2000", "--warm", "200", "--modelos", "ftrl",
        "--destino", str(dados), "--saida", str(tmp_path), "--silencioso",
    ])
    assert codigo == 0
    _, linhas = _ler_csv(tmp_path / "experimentos.csv")
    assert {l["cenario"] for l in linhas} == {"C1", "C2", "C3", "C4"}


def test_cenario_invalido(tmp_path):
    codigo = main(["--cenario", "C9", "--saida", str(tmp_path)])
    assert codigo == 2


def test_coleta_exige_audit_log_e_rotulos(tmp_path):
    codigo = main(["--fonte", "coleta", "--cenario", "C1",
                   "--saida", str(tmp_path)])
    assert codigo == 2


def _escrever_coleta(tmp_path):
    eventos = [
        {"acao": "aceitar", "confianca": 0.95, "ts": 1, "mac": "x"},
        {"acao": "aceitar", "confianca": 0.90, "ts": 2, "mac": "x"},
        {"acao": "solicitar_mfa", "confianca": 0.80, "ts": 3, "mac": "x"},
        {"acao": "bloquear", "confianca": 0.05, "ts": 4, "mac": "x",
         "latencia_ms": 12.0},
        {"acao": "bloquear", "confianca": 0.10, "ts": 5, "mac": "x",
         "latencia_ms": 14.0},
        {"acao": "solicitar_mfa", "confianca": 0.70, "ts": 6, "mac": "x",
         "latencia_ms": 20.0},
    ]
    log = tmp_path / "eventos.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in eventos) + "\n", encoding="utf-8")
    rotulos = tmp_path / "rotulos.csv"
    rotulos.write_text("rotulo\nlegitimo\n0\n0\nC1\nC1\nC1\n", encoding="utf-8")
    return log, rotulos


def test_coleta_calcula_metricas(tmp_path):
    log, rotulos = _escrever_coleta(tmp_path)
    assert len(ler_auditoria(log)) == 6
    assert ler_rotulos(rotulos) == [0, 0, 0, 1, 1, 1]

    codigo = main([
        "--fonte", "coleta", "--cenario", "C1",
        "--audit-log", str(log), "--rotulos", str(rotulos),
        "--saida", str(tmp_path / "out"), "--silencioso",
    ])
    assert codigo == 0
    _, linhas = _ler_csv(tmp_path / "out" / "experimentos.csv")
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["fonte"] == "coleta"
    assert linha["modelo"] == "sistema"
    assert linha["cenario"] == "C1"
    assert float(linha["tpr"]) == 1.0
    assert float(linha["fpr"]) == 0.0
    assert int(linha["eventos"]) == 6
    assert linha["bloqueios"] == "2" and linha["escaladas"] == "1"
    assert float(linha["lat_p95_ms"]) == pytest.approx(19.4)


def test_coleta_tamanhos_diferentes_falha(tmp_path):
    log, rotulos = _escrever_coleta(tmp_path)
    rotulos.write_text("rotulo\n0\n0\n", encoding="utf-8")
    codigo = main([
        "--fonte", "coleta", "--cenario", "C1",
        "--audit-log", str(log), "--rotulos", str(rotulos),
        "--saida", str(tmp_path / "out"),
    ])
    assert codigo == 2


def test_coleta_acao_desconhecida_falha(tmp_path):
    log = tmp_path / "eventos.jsonl"
    log.write_text(json.dumps({"acao": "aprovar", "confianca": 0.5}) + "\n",
                   encoding="utf-8")
    rotulos = tmp_path / "rotulos.csv"
    rotulos.write_text("rotulo\nlegitimo\n", encoding="utf-8")
    eventos = ler_auditoria(log)
    with pytest.raises(ValueError, match="acao desconhecida"):
        executar_coleta("C1", eventos, [0])

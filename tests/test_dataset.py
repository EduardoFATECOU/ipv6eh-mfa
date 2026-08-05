"""Testes do gerador do dataset IPv6-EH (Anexo B)."""

import csv
import json
from pathlib import Path

import pytest

from attacks.generate_dataset import (
    COLUNAS,
    N_ATAQUE_POR_CENARIO,
    N_LEGITIMO,
    TOTAL,
    gerar_dataset,
    validar,
)
from attacks.scenarios import CENARIOS, codigo_para_id, validar_cenario


def test_cenarios_na_tese():
    assert validar_cenario("C1").nome == "Roubo de Credenciais"
    assert validar_cenario("C2").nome == "Man-in-the-Middle"
    assert validar_cenario("C3").nome == "Replay de Autenticacao"
    assert validar_cenario("C4").nome == "Spoofing de Agente"
    assert codigo_para_id(2) == "C2"
    with pytest.raises(KeyError):
        codigo_para_id(9)


def test_totais():
    assert TOTAL == N_LEGITIMO + 4 * N_ATAQUE_POR_CENARIO == 500_000


def test_colunas_anexo_b6():
    assert COLUNAS[0] == "hora_dia"
    assert "localizacao" in COLUNAS
    assert "flow_label" in COLUNAS
    assert "versao_eh" in COLUNAS
    assert "confianca_fator" in COLUNAS
    assert COLUNAS[-1] == "rotulo"


def test_gerar_dataset_pequeno(tmp_path):
    resumo = gerar_dataset(tmp_path, n_legitimo=1000, n_ataque=200, seed=7)
    assert resumo["legitimo"]["linhas"] == 1000
    for cod in (1, 2, 3, 4):
        assert resumo[f"c{cod}"]["linhas"] == 200

    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta["total_eventos"] == 1000 + 4 * 200
    assert meta["seed_base"] == 7
    assert "legitimo" in meta["sementes"]

    # cabecalho fiel ao Anexo B.6
    with open(tmp_path / "legitimo.csv", newline="", encoding="utf-8") as fh:
        leitor = csv.reader(fh)
        cabecalho = next(leitor)
        assert cabecalho == COLUNAS

    checagem = validar(tmp_path)
    assert checagem["total"] == 1000 + 4 * 200
    assert checagem["nao_numerico"] == 0
    assert checagem["por_rotulo"]["0"] == 1000


def test_gerar_dataset_deterministico(tmp_path):
    a = gerar_dataset(tmp_path / "a", n_legitimo=500, n_ataque=100, seed=3)
    b = gerar_dataset(tmp_path / "b", n_legitimo=500, n_ataque=100, seed=3)
    for nome in ("legitimo", "c1", "c2", "c3", "c4"):
        assert (tmp_path / "a" / f"{nome}.csv").read_bytes() == (
            tmp_path / "b" / f"{nome}.csv"
        ).read_bytes()

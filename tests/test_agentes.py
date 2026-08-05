"""Testes dos cenarios de ataque (C1-C4) e agentes (esqueletos)."""

import pytest

from attacks.scenarios import CENARIOS, validar_cenario
from aa_agent.agent import Auditoria
from ad_agent.agent import ModelPolicy, RuleBasedPolicy


def test_cenarios_completos():
    assert set(CENARIOS) == {"C1", "C2", "C3", "C4"}
    for c in CENARIOS.values():
        assert c.id and c.nome and c.descricao
        assert c.parametros.get("reps") == 30


def test_validar_cenario():
    assert validar_cenario("C2").id == "C2"
    with pytest.raises(KeyError):
        validar_cenario("C9")


def test_rule_based_policy():
    p = RuleBasedPolicy(limiar_alto=0.9, limiar_baixo=0.6)
    assert p.decidir({"confianca": 0.95, "risco": 0.1})["acao"] == "aceitar"
    assert p.decidir({"confianca": 0.3, "risco": 0.1})["acao"] == "bloquear"
    assert p.decidir({"confianca": 0.7, "risco": 0.5})["acao"] == "solicitar_mfa"


def test_auditoria_registro_com_hmac(tmp_path):
    aud = Auditoria(chave=b"chave-teste", caminho=tmp_path)
    reg = aud.registrar({"acao": "aceitar", "confianca": 0.9, "ts": 1})
    assert "mac" in reg
    destino = aud.persistir("eventos.jsonl")
    assert destino.exists()
    conteudo = destino.read_text(encoding="utf-8")
    assert "aceitar" in conteudo

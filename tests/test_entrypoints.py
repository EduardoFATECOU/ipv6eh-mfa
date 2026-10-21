# -*- coding: utf-8 -*-
"""Testes dos entrypoints ``python -m <agente>``.

O modo ``--check`` valida a configuracao sem conectar ao XMPP, o que permite
testar os entrypoints em CI (onde SPADE nao esta instalado).
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

SPADE_INSTALADO = importlib.util.find_spec("spade") is not None


def _check(modulo: str, *extras: str, env: dict | None = None) -> subprocess.CompletedProcess:
    ambiente = dict(os.environ)
    if env:
        ambiente.update(env)
    return subprocess.run(
        [sys.executable, "-m", modulo, "--check", *extras],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=120,
        env=ambiente,
    )


@pytest.mark.parametrize("modulo", ["am_agent", "ad_agent", "aa_agent"])
def test_check_valida_configuracao(modulo):
    proc = _check(modulo)
    assert proc.returncode == 0, proc.stderr
    assert "configuracao OK" in proc.stdout
    assert f"{modulo}:" in proc.stdout


def test_check_respeita_mfa_jid():
    proc = _check("am_agent", env={"MFA_JID": "teste@localhost"})
    assert proc.returncode == 0, proc.stderr
    assert "jid=teste@localhost" in proc.stdout


def test_aa_aceita_diretorio_de_auditoria(tmp_path):
    proc = _check("aa_agent", "--audit-dir", str(tmp_path))
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(SPADE_INSTALADO, reason="SPADE instalado: o agente tentaria conectar")
def test_sem_spade_retorna_codigo_de_erro():
    proc = subprocess.run(
        [sys.executable, "-m", "am_agent", "--jid", "teste@localhost"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 2
    assert "SPADE nao instalado" in proc.stderr

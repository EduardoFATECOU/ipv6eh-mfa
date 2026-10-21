# -*- coding: utf-8 -*-
"""Testes do ``deploy_vms.sh`` (sintaxe, ajuda, modos e ``--dry-run``)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "deploy_vms.sh"


def _achar_bash() -> str | None:
    encontrado = shutil.which("bash")
    if encontrado:
        return encontrado
    for caminho in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        if os.path.exists(caminho):
            return caminho
    return None


BASH = _achar_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="bash indisponivel")


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    ambiente = dict(os.environ)
    if env:
        ambiente.update(env)
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=60,
        env=ambiente,
    )


def test_sintaxe():
    proc = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_ajuda():
    proc = _run("--help")
    assert proc.returncode == 0, proc.stderr
    assert "aws" in proc.stdout and "local" in proc.stdout
    assert "--dry-run" in proc.stdout


def test_modo_invalido():
    proc = _run("foo")
    assert proc.returncode == 2
    assert "modo deve ser" in proc.stderr


def test_dry_run_lista_as_4_vms():
    proc = _run("local", "--dry-run", env={"MFA_KEY": ""})
    assert proc.returncode == 0, proc.stderr
    saida = proc.stdout
    for ip in ("192.168.1.10", "192.168.1.11", "192.168.1.12", "192.168.1.13"):
        assert ip in saida
    assert "monitor1@lars.local" in saida
    assert "decisor@lars.local" in saida
    assert "auditor@lars.local" in saida
    assert "servico systemd" in saida


def test_aws_sem_chave_falha():
    proc = _run("aws", "--dry-run", env={"MFA_KEY": ""})
    assert proc.returncode == 2
    assert "exige --key" in proc.stderr


def test_hosts_incompletos_falha():
    proc = _run("local", "--dry-run", "--hosts", "10.0.0.1 10.0.0.2", env={"MFA_KEY": ""})
    assert proc.returncode == 2
    assert "esperados 4 hosts" in proc.stderr

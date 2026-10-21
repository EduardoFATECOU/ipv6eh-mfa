"""Testes do verificador de ambiente das VMs (Fase 0.7)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
VERIFICAR = RAIZ / "verificar_ambiente.sh"
DEPLOY = RAIZ / "deploy_vms.sh"

TODOS_OS_SKIPS = [
    "--skip-sistema",
    "--skip-deps",
    "--skip-agente",
    "--skip-ipv6",
    "--skip-ntp",
    "--skip-ipsec",
    "--skip-xmpp",
]


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


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(script), *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_sintaxe():
    proc = subprocess.run([BASH, "-n", str(VERIFICAR)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_help_documenta_opcoes():
    proc = _run(VERIFICAR, "--help")
    assert proc.returncode == 0, proc.stderr
    for trecho in ("--ipv6-iface", "--ipv6-peers", "--esperadas", "--max-offset",
                   "--skip-ipsec", "--skip-xmpp", "--xmpp-host"):
        assert trecho in proc.stdout


def test_opcao_invalida():
    proc = _run(VERIFICAR, "--nao-existe")
    assert proc.returncode == 2
    assert "desconhecida" in proc.stderr


def test_opcao_sem_valor():
    proc = _run(VERIFICAR, "--projeto")
    assert proc.returncode == 2
    assert "exige um valor" in proc.stderr


def test_tudo_desativado_e_erro():
    proc = _run(VERIFICAR, *TODOS_OS_SKIPS)
    assert proc.returncode == 2
    assert "nada a fazer" in proc.stderr


def test_somente_sistema_nao_reprova():
    """Fora da VM (Windows/CI) o setor Sistema nao deve gerar FALHA."""
    proc = _run(
        VERIFICAR,
        "--skip-deps",
        "--skip-agente",
        "--skip-ipv6",
        "--skip-ntp",
        "--skip-ipsec",
        "--skip-xmpp",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "== Sistema ==" in proc.stdout
    assert "[FALHA]" not in proc.stdout
    assert "Ambiente pronto" in proc.stdout


def test_falhas_reprovam_o_ambiente():
    """Sem StrongSwan/XMPP o verificador deve reprovar (exit 1)."""
    proc = _run(
        VERIFICAR,
        "--ipv6-peers",
        "2001:db8:2::11",
        "--xmpp-host",
        "127.0.0.1",
        "--xmpp-port",
        "1",
    )
    assert proc.returncode == 1
    assert "[FALHA]" in proc.stdout
    assert "Ambiente NAO esta pronto" in proc.stdout
    assert "Resumo:" in proc.stdout


def test_skip_xmpp_remove_secao():
    proc = _run(
        VERIFICAR,
        "--skip-sistema",
        "--skip-deps",
        "--skip-agente",
        "--skip-ipv6",
        "--skip-ntp",
        "--skip-ipsec",
        "--xmpp-host",
        "127.0.0.1",
        "--xmpp-port",
        "1",
    )
    assert proc.returncode == 1
    assert "== XMPP ==" in proc.stdout
    assert "TCP 127.0.0.1:1 inacessivel" in proc.stdout

    proc = _run(
        VERIFICAR,
        "--skip-deps",
        "--skip-agente",
        "--skip-ipv6",
        "--skip-ntp",
        "--skip-ipsec",
        "--skip-xmpp",
    )
    assert proc.returncode == 0
    assert "== Sistema ==" in proc.stdout
    assert "== XMPP ==" not in proc.stdout


def test_deploy_dry_run_executa_verificador():
    proc = _run(DEPLOY, "local", "--dry-run", "--ipv6-iface", "enp0s8")
    assert proc.returncode == 0, proc.stderr
    assert "verificador de ambiente" in proc.stdout
    assert "bash verificar_ambiente.sh --ipv6-iface enp0s8" in proc.stdout


def test_deploy_skip_verificador():
    proc = _run(DEPLOY, "local", "--dry-run", "--skip-verificador")
    assert proc.returncode == 0, proc.stderr
    assert "verificador de ambiente" not in proc.stdout


def test_deploy_skip_ipsec_propaga_para_o_verificador():
    proc = _run(DEPLOY, "local", "--dry-run", "--skip-ipsec")
    assert proc.returncode == 0, proc.stderr
    assert "bash verificar_ambiente.sh --skip-ipsec" in proc.stdout

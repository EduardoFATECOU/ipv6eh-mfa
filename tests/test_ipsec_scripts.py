"""Testes dos scripts de PKI/IPSec (Fase 0.5)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PKI = RAIZ / "ipsec" / "pki.sh"
GERAR = RAIZ / "ipsec" / "gerar_conf.sh"
DEPLOY = RAIZ / "deploy_vms.sh"
TEMPLATE = RAIZ / "ipsec" / "ipsec.conf"


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


def _run(script: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    ambiente = dict(os.environ)
    if env:
        ambiente.update(env)
    return subprocess.run(
        [BASH, str(script), *args],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=60,
        env=ambiente,
    )


@pytest.mark.parametrize("script", [PKI, GERAR])
def test_sintaxe(script):
    proc = subprocess.run([BASH, "-n", str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_template_transporte_e_lifetime():
    texto = TEMPLATE.read_text(encoding="utf-8")
    assert "type=transport" in texto
    assert "type=tunnel" not in texto
    assert "esp=aes256gcm16-ecp256" in texto
    assert "lifetime=8h" in texto
    assert "lifebytes=104857600" in texto
    assert "@NOME@" in texto and "@IPV6@" in texto


def test_pki_dry_run_lista_ca_e_quatro_vms():
    proc = _run(PKI, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    saida = proc.stdout
    assert "ipsec pki --self --ca" in saida
    assert "--type ecdsa --size 256" in saida
    for nome in ("cliente", "servidor", "gateway", "auditor"):
        assert f"{nome}.lars.local" in saida
    assert "--flag serverAuth --flag clientAuth" in saida
    assert saida.count("ipsec pki --issue") == 4


def test_pki_exige_quatro_hosts():
    proc = _run(PKI, "--dry-run", "--hosts", "a b", env={"MFA_KEY": ""})
    assert proc.returncode == 2
    assert "4 nomes" in proc.stderr


@pytest.mark.parametrize(
    "nome,ipv6",
    [
        ("cliente", "2001:db8:1::10"),
        ("servidor", "2001:db8:2::11"),
        ("gateway", "2001:db8:2::12"),
        ("auditor", "2001:db8:2::13"),
    ],
)
def test_gerar_conf_por_vm(nome, ipv6):
    proc = _run(GERAR, "--host", nome)
    assert proc.returncode == 0, proc.stderr
    saida = proc.stdout

    assert f"left={ipv6}" in saida
    assert f"leftcert=/etc/ipsec.d/certs/{nome}-cert.pem" in saida
    assert "type=transport" in saida
    assert "auto=start" in saida
    assert "@NOME@" not in saida and "@IPV6@" not in saida and "@DOMINIO@" not in saida

    conns = [l for l in saida.splitlines() if l.startswith("conn mfa-")]
    assert len(conns) == 3
    assert f"conn mfa-{nome}" not in saida
    for peer in ("cliente", "servidor", "gateway", "auditor"):
        if peer == nome:
            continue
        assert f"conn mfa-{peer}" in saida
        assert f"rightid={peer}.lars.local" in saida
        assert f"rightcert=/etc/ipsec.d/certs/{peer}-cert.pem" in saida


def test_gerar_conf_host_desconhecido_exige_dados():
    proc = _run(GERAR, "--host", "vm9")
    assert proc.returncode == 2
    assert "fora da tabela" in proc.stderr


def test_gerar_conf_host_customizado():
    proc = _run(
        GERAR, "--host", "vm9", "--ipv6", "2001:db8:9::5",
        "--peers", "cliente=2001:db8:1::10 gateway=2001:db8:2::12",
    )
    assert proc.returncode == 0, proc.stderr
    saida = proc.stdout
    assert "left=2001:db8:9::5" in saida
    assert "leftcert=/etc/ipsec.d/certs/vm9-cert.pem" in saida
    assert saida.count("conn mfa-") == 2
    assert "right=2001:db8:1::10" in saida


def test_deploy_dry_run_inclui_ipsec():
    proc = _run(DEPLOY, "local", "--dry-run", "--ipv6-iface", "enp0s8")
    assert proc.returncode == 0, proc.stderr
    saida = proc.stdout
    assert "certificados X.509" in saida
    assert "ipsec.conf de cliente" in saida
    assert "ip -6 addr replace 2001:db8:1::10/64 dev enp0s8" in saida
    assert "sudo ipsec statusall" in saida


def test_deploy_dry_run_instala_ca_no_auditor():
    proc = _run(DEPLOY, "local", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "CA mantida pelo AA" in proc.stdout


def test_deploy_skip_ipsec():
    proc = _run(DEPLOY, "local", "--dry-run", "--skip-ipsec")
    assert proc.returncode == 0, proc.stderr
    assert "certificados X.509" not in proc.stdout
    assert "ipsec statusall" not in proc.stdout


def test_deploy_help_documenta_novas_flags():
    proc = _run(DEPLOY, "--help")
    assert proc.returncode == 0, proc.stderr
    assert "--skip-ipsec" in proc.stdout
    assert "--ipv6-iface" in proc.stdout
    assert "--ipv6" in proc.stdout
    assert "ipsec/pki.sh" in proc.stdout


def test_deploy_dry_run_usa_ipv6_da_vpc():
    """No AWS os IPv6 vem da VPC: --ipv6 usa os enderecos sem adiciona-los."""
    ips = "2600:1f18:aa::10 2600:1f18:aa::11 2600:1f18:aa::12 2600:1f18:aa::13"
    proc = _run(DEPLOY, "local", "--dry-run", "--ipv6", ips)
    assert proc.returncode == 0, proc.stderr
    assert "ip -6 addr" not in proc.stdout
    assert "2600:1f18:aa::10" in proc.stdout
    assert "--ipv6-peers 2600:1f18:aa::11 2600:1f18:aa::12 2600:1f18:aa::13" in proc.stdout


def test_deploy_ipv6_invalido():
    proc = _run(DEPLOY, "local", "--dry-run", "--ipv6", "a b")
    assert proc.returncode == 2
    assert "4 enderecos" in proc.stderr

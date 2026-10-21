"""Ponto de entrada compartilhado dos agentes AM/AD/AA.

Uso (systemd ou terminal)::

    python -m am_agent
    python -m ad_agent
    python -m aa_agent

Configuracao por variaveis de ambiente (ou flags equivalentes):

    MFA_JID            JID XMPP do agente (obrigatorio)
    MFA_PASSWORD       senha do JID XMPP (padrao: "secret")
    MFA_LOG_LEVEL      nivel de log (padrao: INFO)
    MFA_AUTO_REGISTER  "1" para auto-registrar a conta no servidor XMPP
    MFA_AD_JID         JID do Agente Decisor (usado pelo AM)
    MFA_AA_JID         JID do Agente Auditoria (usado pelo AD)
    MFA_AUDIT_DIR      diretorio dos registros do AA
    MFA_AUDIT_KEY      chave HMAC do AA em hexadecimal (32 bytes)

``--check`` valida a configuracao e encerra sem conectar ao XMPP (util em CI).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

_FORMATO_LOG = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def env(nome: str, padrao: str | None = None) -> str | None:
    """Le uma variavel de ambiente tratando string vazia como ausente."""
    valor = os.environ.get(nome)
    return valor if valor not in (None, "") else padrao


def _bool_env(nome: str, padrao: bool = True) -> bool:
    valor = env(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def run_agent(
    nome: str,
    modulo,
    *,
    jid_padrao: str | None = None,
    descricao: str = "",
    argumentos=None,
) -> int:
    """Configura e inicia um agente SPADE.

    ``modulo`` deve expor ``build_agent(jid, password, **kwargs)`` e
    ``SPADE_AVAILABLE`` (convencao dos pacotes ``*_agent``).
    """
    parser = argparse.ArgumentParser(prog=f"python -m {nome}", description=descricao or nome)
    parser.add_argument("--jid", default=env("MFA_JID", jid_padrao), help="JID XMPP do agente")
    parser.add_argument("--password", default=env("MFA_PASSWORD", "secret"), help="senha do JID")
    parser.add_argument(
        "--log-level",
        default=env("MFA_LOG_LEVEL", "INFO"),
        help="DEBUG, INFO, WARNING, ERROR (padrao: INFO)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="valida a configuracao e encerra sem conectar ao XMPP",
    )
    parser.add_argument(
        "--auto-register",
        action=argparse.BooleanOptionalAction,
        default=_bool_env("MFA_AUTO_REGISTER", True),
        help="registra o JID automaticamente no servidor XMPP",
    )
    if argumentos is not None:
        argumentos(parser)
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format=_FORMATO_LOG,
    )
    logger = logging.getLogger(nome)

    if not args.jid:
        parser.error("informe --jid ou defina MFA_JID")

    spade_ok = bool(getattr(modulo, "SPADE_AVAILABLE", False))

    if args.check:
        print(
            f"{nome}: configuracao OK (jid={args.jid}, "
            f"spade={'instalado' if spade_ok else 'ausente'})"
        )
        if not spade_ok:
            print(
                f"{nome}: aviso: SPADE ausente; instale requirements-vm.txt "
                "no servidor de experimentos"
            )
        return 0

    if not spade_ok:
        print(
            f"{nome}: erro: SPADE nao instalado (pip install -r requirements-vm.txt)",
            file=sys.stderr,
        )
        return 2

    kwargs: dict = {}
    if hasattr(args, "audit_dir"):
        kwargs["caminho"] = args.audit_dir
    if hasattr(args, "audit_key") and args.audit_key:
        try:
            kwargs["chave"] = bytes.fromhex(args.audit_key)
        except ValueError:
            parser.error("--audit-key deve estar em hexadecimal")

    logger.info("iniciando %s", args.jid)
    try:
        agente = modulo.build_agent(args.jid, args.password, **kwargs)
        agente.start(auto_register=args.auto_register)
    except KeyboardInterrupt:
        logger.info("encerrando %s", args.jid)
        return 0
    return 0

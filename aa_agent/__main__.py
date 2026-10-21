"""Executa o Agente Auditoria (AA): ``python -m aa_agent``."""

from agent_entry import env, run_agent

from aa_agent import agent as modulo


def _argumentos(parser) -> None:
    parser.add_argument(
        "--audit-dir",
        default=env("MFA_AUDIT_DIR", "logs"),
        help="diretorio dos registros de auditoria (padrao: logs)",
    )
    parser.add_argument(
        "--audit-key",
        default=env("MFA_AUDIT_KEY"),
        help="chave HMAC do AA em hexadecimal",
    )


if __name__ == "__main__":
    raise SystemExit(
        run_agent(
            "aa_agent",
            modulo,
            jid_padrao="auditor@localhost",
            descricao="Agente Auditoria (AA) - registro HMAC das decisoes",
            argumentos=_argumentos,
        )
    )

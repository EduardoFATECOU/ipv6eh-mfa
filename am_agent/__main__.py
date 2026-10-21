"""Executa o Agente Monitor (AM): ``python -m am_agent``."""

from agent_entry import run_agent

from am_agent import agent as modulo

if __name__ == "__main__":
    raise SystemExit(
        run_agent(
            "am_agent",
            modulo,
            jid_padrao="monitor@localhost",
            descricao="Agente Monitor (AM) - coleta continua de credenciais e features",
        )
    )

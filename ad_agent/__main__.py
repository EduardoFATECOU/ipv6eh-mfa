"""Executa o Agente Decisor (AD): ``python -m ad_agent``."""

from agent_entry import run_agent

from ad_agent import agent as modulo

if __name__ == "__main__":
    raise SystemExit(
        run_agent(
            "ad_agent",
            modulo,
            jid_padrao="decisor@localhost",
            descricao="Agente Decisor (AD) - politica adaptativa de autenticacao",
        )
    )

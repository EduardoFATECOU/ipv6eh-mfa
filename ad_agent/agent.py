"""Agente Decisor (AD) - decisao adaptativa de autenticacao continua.

Responsabilidades (Cap. 7):
  - recebe o estado publicado pelo AM (confiancas + contexto de risco);
  - executa a politica de decisao: FTRL/ARF (classificacao de sessao)
    e DQN (selecao de acao de fator/risco, 10 dimensoes x 25 acoes);
  - emite a ordem para o Agente Auditoria (AA) e, se preciso, dispara
    o desafio MFA (TOTP/biometria) via StrongSwan eXAuth;
  - mantem o oraculo de confianca (CVR/FPR) usado no Cap. 8.

A politica e plugavel (PolicyStrategy): permite trocar FTRL/ARF/DQN
sem alterar o agente.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger("ad_agent")

try:
    import spade

    SPADE_AVAILABLE = True
    CyclicBehaviourBase = spade.behaviour.CyclicBehaviour
    AgentBase = spade.Agent
except ImportError:  # pragma: no cover - ambiente sem SPADE
    spade = None
    SPADE_AVAILABLE = False
    CyclicBehaviourBase = object
    AgentBase = object

from ml.models import OnlineModel


class PolicyStrategy:
    """Interface da politica de decisao do Agente Decisor."""

    def decidir(self, estado: dict) -> dict:
        """Recebe o estado e retorna {acao, confianca, justificativa}."""
        raise NotImplementedError


class RuleBasedPolicy(PolicyStrategy):
    """Politica de regras usada como baseline (C1) e fallback."""

    def __init__(self, limiar_alto: float = 0.9, limiar_baixo: float = 0.6):
        self.limiar_alto = limiar_alto
        self.limiar_baixo = limiar_baixo

    def decidir(self, estado: dict) -> dict:
        conf = estado.get("confianca", 0.0)
        risco = estado.get("risco", 0.0)
        if conf >= self.limiar_alto and risco < 0.5:
            return {"acao": "aceitar", "confianca": conf, "justificativa": "confianca alta"}
        if conf < self.limiar_baixo or risco > 0.8:
            return {"acao": "bloquear", "confianca": conf, "justificativa": "confianca baixa/risco alto"}
        return {"acao": "solicitar_mfa", "confianca": conf, "justificativa": "verificacao adicional"}


class ModelPolicy(PolicyStrategy):
    """Politica baseada em modelo online (FTRL/ARF)."""

    def __init__(self, model: OnlineModel, limiar: float = 0.5):
        self.model = model
        self.limiar = limiar

    def decidir(self, estado: dict) -> dict:
        x = {k: v for k, v in estado.items() if isinstance(v, float)}
        proba = self.model.predict_proba_one(x)
        conf = proba.get(1, 0.0)
        if conf >= self.limiar:
            return {"acao": "aceitar", "confianca": conf, "justificativa": "modelo"}
        return {"acao": "solicitar_mfa", "confianca": conf, "justificativa": "modelo"}


class DecisorBehavior(CyclicBehaviourBase):  # type: ignore[misc]
    async def run(self):
        msg = await self.receive(timeout=1.0)
        if msg is None:
            return
        agent: "DecisorAgent" = self.agent  # type: ignore[assignment]
        estado = agent.interpretar(msg.body)
        decisao = agent.politica.decidir(estado)
        LOGGER.info("decisao=%s conf=%.3f", decisao["acao"], decisao["confianca"])
        resposta = spade.message.Message(
            to="auditor@localhost",
            body=f"decisao|{decisao['acao']}|{decisao['confianca']}|{decisao['justificativa']}",
        )
        await self.send(resposta)


class DecisorAgent(AgentBase):  # type: ignore[misc]
    """Agente Decisor: esqueleto com politica plugavel."""

    def __init__(self, jid, password, *, politica: PolicyStrategy = None):
        super().__init__(jid, password)
        self.politica = politica or RuleBasedPolicy()

    def interpretar(self, corpo: str) -> dict:
        """Converte a mensagem do AM (pipe-separated) em estado dict."""
        partes = corpo.split("|")
        estado = {"confianca": float(partes[2]) if len(partes) > 2 else 0.0}
        if len(partes) > 3 and partes[3]:
            for par in partes[3].split(","):
                if "=" in par:
                    k, v = par.split("=", 1)
                    try:
                        estado[k] = float(v)
                    except ValueError:
                        estado[k] = v
        return estado

    async def setup(self):
        self.add_behaviour(DecisorBehavior())
        LOGGER.info("DecisorAgent %s iniciado", self.jid)


def build_agent(jid: str, password: str = "secret", **kwargs) -> "DecisorAgent":
    if not SPADE_AVAILABLE:
        raise RuntimeError("spade nao esta instalado (pip install spade)")
    return DecisorAgent(jid, password, **kwargs)

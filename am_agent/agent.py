"""Agente Monitor (AM) - coleta e preprocessa os dados de autenticacao.

Responsabilidades (Cap. 7):
  - escuta a opcao MFA (Destination Options, otype 0x1E) no trafego IPv6
    do cliente, por meio de sniffer Scapy ou do plugin do StrongSwan;
  - extrai e decodifica a credencial (protocol.mfa_option.parse_option_data);
  - calcula features em janelas deslizantes (velocidade de digitacao,
    latencia inter-key, movimentacao do mouse, telemetria ESP/AH);
  - publica o estado no XMPP (SPADE) para o Agente Decisor.

No ambiente de experimentacao (4 VMs), o AM roda na VM do cliente/servidor
como daemon (systemd). Aqui ficam o esqueleto e os comportamentos SPADE.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger("am_agent")

try:
    import spade

    SPADE_AVAILABLE = True
    PeriodicBehaviourBase = spade.behaviour.PeriodicBehaviour
    AgentBase = spade.Agent
except ImportError:  # pragma: no cover - ambiente sem SPADE
    spade = None
    SPADE_AVAILABLE = False
    PeriodicBehaviourBase = object
    AgentBase = object


from protocol.replay import ReplayDefender


class MonitorBehavior(PeriodicBehaviourBase):  # type: ignore[misc]
    """Coleta periodica das features e publicacao do estado no XMPP."""

    async def run(self):
        agent: "MonitorAgent" = self.agent  # type: ignore[assignment]
        credencial = agent.coletar_credencial()
        if credencial is None:
            return

        # Verifica replay
        if not agent.defender.is_valid(credencial):
            LOGGER.warning("Ataque de replay detectado!")
            features = agent.calcular_features()
            msg = spade.message.Message(
                to="decisor@localhost",
                body=f"estado|{credencial.timestamp}|0.0|ataque=replay,{features}",
            )
            await self.send(msg)
            return

        features = agent.calcular_features()
        msg = spade.message.Message(
            to="decisor@localhost",
            body=f"estado|{credencial.timestamp}|{credencial.confidence}|{features}",
        )
        await self.send(msg)
        LOGGER.debug("estado publicado: fator=%s conf=%s", credencial.factor_type, credencial.confidence)


class MonitorAgent(AgentBase):  # type: ignore[misc]
    """Agente Monitor: esqueleto com o fluxo principal de coleta."""

    def __init__(self, jid, password, *, coleta=None, features=None):
        super().__init__(jid, password)
        self._coleta = coleta or (lambda: None)
        self._features = features or (lambda: {})
        self.defender = ReplayDefender()

    def coletar_credencial(self):
        """Decodifica a credencial MFA do trafego (injetado via Scapy)."""
        return self._coleta()

    def calcular_features(self):
        """Gera as features de comportamento a partir da janela corrente."""
        return self._features()

    async def setup(self):
        behavior = MonitorBehavior(period=1.0)
        self.add_behaviour(behavior)
        LOGGER.info("MonitorAgent %s iniciado", self.jid)


def build_agent(jid: str, password: str = "secret", **kwargs) -> "MonitorAgent":
    if not SPADE_AVAILABLE:
        raise RuntimeError("spade nao esta instalado (pip install spade)")
    return MonitorAgent(jid, password, **kwargs)

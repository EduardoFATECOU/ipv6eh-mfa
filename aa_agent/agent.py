"""Agente Auditoria (AA) - registro e analise das decisoes.

Responsabilidades (Cap. 7):
  - persiste cada decisao do AD em log assinado (integridade via HMAC);
  - calcula metricas de avaliacao online: CVR, FPR, AUC, EER;
  - aciona a reavaliacao do modelo quando detecta drift (via ADWIN),
    mantendo o registro para o Cap. 8 (tabelas 8.1-8.7).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path

LOGGER = logging.getLogger("aa_agent")

try:
    import spade

    SPADE_AVAILABLE = True
    BehaviourBase = spade.behaviour.CyclicBehaviour
    AgentBase = spade.Agent
except ImportError:  # pragma: no cover - ambiente sem SPADE
    spade = None
    SPADE_AVAILABLE = False
    BehaviourBase = object
    AgentBase = object


class Auditoria:
    """Nucleo independente de SPADE (testavel sem XMPP)."""

    def __init__(self, chave: bytes, caminho: Path):
        self.chave = chave
        self.caminho = Path(caminho)
        self.caminho.mkdir(parents=True, exist_ok=True)
        self.eventos = []
        self._adwin = None

    @staticmethod
    def _mac(registro: str, chave: bytes) -> str:
        return hmac.new(chave, registro.encode("utf-8"), hashlib.sha256).hexdigest()

    def registrar(self, decisao: dict) -> dict:
        """Registra a decisao com HMAC e retorna o registro completo."""
        registro = {
            "acao": decisao["acao"],
            "confianca": decisao.get("confianca"),
            "justificativa": decisao.get("justificativa"),
            "ts": decisao.get("ts", 0),
        }
        corpo = json.dumps(registro, sort_keys=True, ensure_ascii=False)
        registro["mac"] = self._mac(corpo, self.chave)
        self.eventos.append(registro)
        return registro

    def persistir(self, nome: str = "eventos.jsonl") -> Path:
        destino = self.caminho / nome
        with open(destino, "a", encoding="utf-8") as fh:
            for evento in self.eventos[-1:]:
                fh.write(json.dumps(evento, ensure_ascii=False) + "\n")
        return destino


class AuditoriaBehavior(BehaviourBase):  # type: ignore[misc]
    async def run(self):
        msg = await self.receive(timeout=1.0)
        if msg is None:
            return
        agent: "AuditoriaAgent" = self.agent  # type: ignore[assignment]
        partes = msg.body.split("|")
        if partes[0] != "decisao":
            return
        decisao = {
            "acao": partes[1],
            "confianca": float(partes[2]) if len(partes) > 2 else None,
            "justificativa": partes[3] if len(partes) > 3 else "",
        }
        agente.auditoria.registrar(decisao)
        LOGGER.debug("evento registrado: %s", decisao["acao"])


class AuditoriaAgent(AgentBase):  # type: ignore[misc]
    """Agente Auditoria: esqueleto com persistencia HMAC."""

    def __init__(self, jid, password, *, chave: bytes = None, caminho=None):
        super().__init__(jid, password)
        chave = chave or os.urandom(32)
        caminho = caminho or Path("logs")
        self.auditoria = Auditoria(chave=chave, caminho=caminho)

    async def setup(self):
        self.add_behaviour(AuditoriaBehavior())
        LOGGER.info("AuditoriaAgent %s iniciado", self.jid)


def build_agent(jid: str, password: str = "secret", **kwargs) -> "AuditoriaAgent":
    if not SPADE_AVAILABLE:
        raise RuntimeError("spade nao esta instalado (pip install spade)")
    return AuditoriaAgent(jid, password, **kwargs)

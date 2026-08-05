"""Opcao MFA em IPv6 Destination Options (RFC 3692 / RFC 4727).

Codificacao do Option Data (20 bytes), conforme Cap. 5 da tese:

    [0]      factor_type  uint8   1-5 (ver FACTOR_TYPES)
    [1]      version      uint8   0x01 (versao do protocolo)
    [2:4]    confidence   uint16  0-10000 (0,00% - 100,00%)
    [4:8]    timestamp    uint32  Unix epoch (segundos)
    [8:16]   agent_id     uint64  SHA-256 truncado para 64 bits
    [16:20]  nonce        uint32  aleatorio (anti-replay)

O Option Type 0x1E tem os bits 7-6 = 01 (descarta o pacote se nao
reconhecer) e bit 5 = 1 (pode ser alterado em rota), seguindo a regra
da RFC 8200 para atribuicao experimental local.
"""

from __future__ import annotations

import hashlib
import os
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    from scapy.layers.inet6 import IPv6, IPv6ExtHdrDestOpt, HBHOptUnknown
    from scapy.layers.inet6 import TCP, UDP
    SCAPY_AVAILABLE = True
except ImportError:  # pragma: no cover - ambiente sem scapy
    SCAPY_AVAILABLE = False

OPTION_TYPE = 0x1E
OPTION_DATA_LEN = 20
VERSION = 1

#: Tipo de fator de autenticacao (1 byte).
FACTOR_TYPES = {
    1: "senha",
    2: "totp",
    3: "biometria",
    4: "geolocalizacao",
    5: "comportamental",
}
INVERSE_FACTOR_TYPES = {v: k for k, v in FACTOR_TYPES.items()}

#: Confianca do fator, em percentuais de 0.0 a 100.0.
MIN_CONFIDENCE = 0.0
MAX_CONFIDENCE = 100.0
#: Escala interna: confidence int 0-10000 == 0,00%-100,00%.
CONFIDENCE_SCALE = 100

#: Timestamps aceitos (Jan/2000 a Jan/2100, para validacao de sanidade).
MIN_TS = 946684800
MAX_TS = 4102444800


class ProtocolError(ValueError):
    """Erro de codificacao/decodificacao da opcao MFA."""


@dataclass(frozen=True)
class MFACredential:
    """Credencial decodificada de uma opcao MFA."""

    factor_type: int
    version: int
    confidence: float
    timestamp: int
    agent_id: int
    nonce: int
    raw: bytes = field(repr=False)


def agent_id_from_key(key: str | bytes) -> int:
    """Deriva o identificador de 64 bits do agente a partir de uma chave."""
    if isinstance(key, str):
        key = key.encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def build_option_data(
    factor_type: int,
    confidence: float,
    *,
    version: int = VERSION,
    timestamp: Optional[int] = None,
    agent_id: Optional[int] = None,
    agent_key: Optional[str] = None,
    nonce: Optional[int] = None,
    rng=None,
) -> bytes:
    """Monta os 20 bytes do Option Data da opcao MFA.

    O parametro ``agent_id`` tem precedencia sobre ``agent_key``; se nenhum
    for fornecido, o agente recebe o identificador 0 (reservado).
    """
    if factor_type not in FACTOR_TYPES:
        raise ProtocolError(f"factor_type invalido: {factor_type}")
    if version < 0 or version > 255:
        raise ProtocolError(f"version fora do intervalo: {version}")
    if not (MIN_CONFIDENCE <= confidence <= MAX_CONFIDENCE):
        raise ProtocolError(
            f"confidence fora do intervalo: {confidence}"
        )
    ts = timestamp if timestamp is not None else int(time.time())
    if not (MIN_TS <= ts <= MAX_TS):
        raise ProtocolError(f"timestamp fora do intervalo: {ts}")
    if agent_id is None:
        agent_id = agent_id_from_key(agent_key) if agent_key else 0
    if not (0 <= agent_id < (1 << 64)):
        raise ProtocolError(f"agent_id fora de uint64: {agent_id}")
    if nonce is None:
        rng = rng or (lambda n: int.from_bytes(os.urandom(n), "big"))
        nonce = rng(4)
    if not (0 <= nonce < (1 << 32)):
        raise ProtocolError(f"nonce fora de uint32: {nonce}")

    conf_int = int(round(confidence * CONFIDENCE_SCALE))
    return struct.pack(
        "!BBHII",
        factor_type,
        version,
        conf_int,
        ts,
        agent_id >> 32,
    ) + struct.pack("!I", agent_id & 0xFFFFFFFF) + struct.pack("!I", nonce)


def parse_option_data(data: bytes) -> MFACredential:
    """Decodifica os 20 bytes do Option Data.

    Raises ProtocolError se o comprimento ou a versao forem invalidos.
    """
    if len(data) != OPTION_DATA_LEN:
        raise ProtocolError(
            f"Option Data deve ter {OPTION_DATA_LEN} bytes, recebeu {len(data)}"
        )
    factor_type, version, conf_int, ts, hi, lo, nonce = struct.unpack(
        "!BBHIIII", data
    )
    if factor_type not in FACTOR_TYPES:
        raise ProtocolError(f"factor_type desconhecido: {factor_type}")
    if version != VERSION:
        raise ProtocolError(
            f"versao do protocolo nao suportada: {version} (esperado {VERSION})"
        )
    confidence = conf_int / CONFIDENCE_SCALE
    return MFACredential(
        factor_type=factor_type,
        version=version,
        confidence=confidence,
        timestamp=ts,
        agent_id=(hi << 32) | lo,
        nonce=nonce,
        raw=data,
    )


def validate(data: bytes) -> None:
    """Valida os bytes sem retornar a credencial (para middleware)."""
    parse_option_data(data)


def make_destopts_packet(
    data: bytes,
    src: str = "2001:db8::1",
    dst: str = "2001:db8::2",
    *,
    next_header: str = "TCP",
    sport: int = 1234,
    dport: int = 500,
) -> object:
    """Monta um pacote IPv6 com a opcao MFA no Destination Options Header.

    Usado nos cenarios C1-C4 para injetar a credencial no trafego
    ESP/AH protegido pelo StrongSwan (RFC 9099).
    """
    if not SCAPY_AVAILABLE:
        raise ProtocolError("scapy nao esta instalado")
    option = HBHOptUnknown(otype=OPTION_TYPE, optlen=OPTION_DATA_LEN, optdata=data)
    destopts = IPv6ExtHdrDestOpt(options=[option], nh=next_header)
    payload = UDP(sport=sport, dport=dport) if next_header == "UDP" else TCP(
        sport=sport, dport=dport
    )
    return IPv6(src=src, dst=dst, nh=60) / destopts / payload


def extract_option_from_packet(pkt) -> Optional[MFACredential]:
    """Extrai e decodifica a primeira opcao MFA de um pacote IPv6."""
    if not SCAPY_AVAILABLE:
        raise ProtocolError("scapy nao esta instalado")
    if pkt.haslayer(IPv6ExtHdrDestOpt):
        for option in pkt[IPv6ExtHdrDestOpt].options:
            if getattr(option, "otype", None) == OPTION_TYPE:
                data = bytes(option.optdata)
                return parse_option_data(data)
    return None


def extract_option_from_bytes(raw: bytes) -> Optional[MFACredential]:
    """Extrai e decodifica a opcao MFA de um datagrama IPv6 cru."""
    if not SCAPY_AVAILABLE:
        raise ProtocolError("scapy nao esta instalado")
    pkt = IPv6(raw)
    return extract_option_from_packet(pkt)


def factor_name(factor_type: int) -> str:
    return FACTOR_TYPES.get(factor_type, f"desconhecido({factor_type})")

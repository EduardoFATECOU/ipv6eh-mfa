"""Testes do modulo protocol/ (opcao MFA em Destination Options)."""

import struct

import pytest

from protocol.mfa_option import (
    CONFIDENCE_SCALE,
    FACTOR_TYPES,
    INVERSE_FACTOR_TYPES,
    MAX_CONFIDENCE,
    MAX_TS,
    MIN_CONFIDENCE,
    MIN_TS,
    OPTION_DATA_LEN,
    OPTION_TYPE,
    VERSION,
    MFACredential,
    ProtocolError,
    agent_id_from_key,
    build_option_data,
    extract_option_from_bytes,
    make_destopts_packet,
    parse_option_data,
)


def test_option_data_len():
    data = build_option_data(1, 0.75, timestamp=1700000000, agent_id=1, nonce=99)
    assert len(data) == OPTION_DATA_LEN == 20


def test_round_trip():
    data = build_option_data(2, 0.65, timestamp=1700000000, agent_id=0x1122334455667788, nonce=0xDEADBEEF)
    cred = parse_option_data(data)
    assert cred.factor_type == 2
    assert cred.version == VERSION
    assert cred.confidence == pytest.approx(0.65)
    assert cred.timestamp == 1700000000
    assert cred.agent_id == 0x1122334455667788
    assert cred.nonce == 0xDEADBEEF


def test_layout_bytes():
    data = build_option_data(5, 100.0, timestamp=1700000000, agent_id=7, nonce=3)
    assert data[0] == 5                      # factor_type
    assert data[1] == VERSION                # version
    assert struct.unpack("!H", data[2:4])[0] == int(100.0 * CONFIDENCE_SCALE)
    assert struct.unpack("!I", data[4:8])[0] == 1700000000
    assert struct.unpack("!Q", data[8:16])[0] == 7
    assert struct.unpack("!I", data[16:20])[0] == 3


def test_fator_invalido():
    with pytest.raises(ProtocolError):
        build_option_data(99, 0.5, timestamp=1700000000)


def test_confianca_fora_do_intervalo():
    with pytest.raises(ProtocolError):
        build_option_data(1, -0.1, timestamp=1700000000)
    with pytest.raises(ProtocolError):
        build_option_data(1, 100.5, timestamp=1700000000)


def test_timestamp_fora_do_intervalo():
    with pytest.raises(ProtocolError):
        build_option_data(1, 0.5, timestamp=MIN_TS - 1)
    with pytest.raises(ProtocolError):
        build_option_data(1, 0.5, timestamp=MAX_TS + 1)


def test_parse_comprimento_invalido():
    with pytest.raises(ProtocolError):
        parse_option_data(b"\x01" * 19)


def test_parse_versao_invalida():
    data = build_option_data(1, 0.5, timestamp=1700000000)
    quebrada = bytes([data[0], data[1] + 9]) + data[2:]
    with pytest.raises(ProtocolError):
        parse_option_data(quebrada)


def test_agent_id_derivado_da_chave():
    a = agent_id_from_key("vm-cliente-01")
    b = agent_id_from_key("vm-cliente-01")
    c = agent_id_from_key("vm-servidor-01")
    assert a == b
    assert a != c
    assert a >= 0 and a < (1 << 64)


def test_nonce_default_diferente():
    n1 = build_option_data(1, 0.5, timestamp=1700000000, agent_id=1, nonce=None)
    n2 = build_option_data(1, 0.5, timestamp=1700000000, agent_id=1, nonce=None)
    assert n1[16:20] != n2[16:20]


def test_extract_de_bytes_round_trip():
    data = build_option_data(3, 0.9, timestamp=1700000000, agent_id=42, nonce=7)
    pkt = make_destopts_packet(data, src="2001:db8::10", dst="2001:db8::20")
    cred = extract_option_from_bytes(bytes(pkt))
    assert cred is not None
    assert isinstance(cred, MFACredential)
    assert cred.factor_type == 3
    assert cred.confidence == pytest.approx(0.9)


def test_extract_sem_opcao():
    from scapy.layers.inet6 import IPv6, IPv6ExtHdrDestOpt, HBHOptUnknown

    pkt = make_destopts_packet(
        build_option_data(1, 0.5, timestamp=1700000000, agent_id=1, nonce=1)
    )
    pkt[IPv6ExtHdrDestOpt].options = [HBHOptUnknown(otype=0x11, optlen=0, optdata=b"")]
    assert extract_option_from_bytes(bytes(pkt)) is None


def test_validate_aceita_bytes_validos():
    data = build_option_data(1, 0.5, timestamp=1700000000, agent_id=1, nonce=1)
    parse_option_data(data)  # sem excecao


def test_fator_name_e_inverso():
    assert INVERSE_FACTOR_TYPES["totp"] == 2
    assert FACTOR_TYPES[5] == "comportamental"

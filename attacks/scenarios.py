"""Definicao dos cenarios de ataque C1-C4 (Cap. 5 §5.5.1 e Cap. 7 da tese).

C1 - Roubo de Credenciais: comprometimento de senha e token TOTP via phishing.
C2 - Man-in-the-Middle: ataque na comunicacao AM-AD (testa IPSec ESP modo
     transporte e deteccao de violacao de SA / replay de pacotes IKE).
C3 - Replay de Autenticacao: reenvio de pacotes IPv6 com metadados MFA antigos
     (capturados ate 24 h antes; testa nonce de 32 bits e timestamp com
     tolerancia maxima de 30 s).
C4 - Spoofing de Agente: agente malicioso tenta registrar-se como AM legitimo
     (testa o modelo Beta Reputation; desvio > 2 desvios padrao leva a
     revogacao do certificado X.509).

Cada cenario e executado em 30 repeticoes independentes; os resultados
alimentam as Tabelas 8.1-8.7. O rotulo do dataset (Anexo B) usa o codigo
numerico do cenario: 0=legitimo, 1=C1, 2=C2, 3=C3, 4=C4.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cenario:
    id: str
    codigo: int
    nome: str
    descricao: str
    parametros: dict = field(default_factory=dict)


CENARIOS = {
    "C1": Cenario(
        id="C1",
        codigo=1,
        nome="Roubo de Credenciais",
        descricao=(
            "Comprometimento de senha e token TOTP via phishing. Espera-se deteccao de "
            "anomalia comportamental (cadencia de digitacao diferente, geolocalizacao "
            "atipica) e exigencia de fator biometrico adicional."
        ),
        parametros={"reps": 30, "janela_s": 600, "confianca_baixa": (0.30, 0.60)},
    ),
    "C2": Cenario(
        id="C2",
        codigo=2,
        nome="Man-in-the-Middle",
        descricao=(
            "Ataque na comunicacao AM-AD. Testa se o IPSec ESP modo transporte impede "
            "interceptacao e se o AA detecta tentativa de violacao de SA (replay de "
            "pacotes IKE)."
        ),
        parametros={"reps": 30, "janela_s": 600, "picos_pacotes_s": (400, 2000)},
    ),
    "C3": Cenario(
        id="C3",
        codigo=3,
        nome="Replay de Autenticacao",
        descricao=(
            "Reenvio de pacotes IPv6 com metadados MFA antigos (capturados ate 24 h "
            "antes). Testa a protecao do nonce (32 bits) e do timestamp (tolerancia "
            "maxima de 30 s)."
        ),
        parametros={"reps": 30, "janela_s": 600, "atraso_captura_h": (0, 24)},
    ),
    "C4": Cenario(
        id="C4",
        codigo=4,
        nome="Spoofing de Agente",
        descricao=(
            "Agente malicioso tenta registrar-se como AM legitimo no AD. Avalia o "
            "modelo Beta Reputation: o AA deve detectar reputacao inconsistente "
            "(desvio > 2 desvios padrao) e revogar o certificado X.509 do agente."
        ),
        parametros={"reps": 30, "janela_s": 600, "desvio_reputacao": 2.0},
    ),
}


def validar_cenario(cenario_id: str) -> Cenario:
    if cenario_id not in CENARIOS:
        raise KeyError(f"cenario desconhecido: {cenario_id}")
    return CENARIOS[cenario_id]


def codigo_para_id(codigo: int) -> str:
    for c in CENARIOS.values():
        if c.codigo == codigo:
            return c.id
    raise KeyError(f"codigo de cenario desconhecido: {codigo}")

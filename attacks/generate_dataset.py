"""Gerador do dataset IPv6-EH (Anexo B da tese).

Gera ~500.000 eventos de autenticacao continua com 10 features contextuais
(derivadas das 10 dimensoes do estado da DQN) e o rotulo da classe:

  hora_dia, dia_semana (7 one-hot), localizacao (geohash de 4 caracteres),
  dispositivo (5 one-hot), hist_autent, taxa_erro, pacotes_s, flow_label,
  versao_eh, confianca_fator, rotulo.

Rotulo: 0 = legitimo; 1 = C1 (Roubo de Credenciais); 2 = C2 (MITM);
3 = C3 (Replay); 4 = C4 (Spoofing de Agente). Cenarios conforme Cap. 5 §5.5.1.

Saida (organizacao do Anexo B.3):
  data/ipv6eh/legitimo.csv, c1.csv ... c4.csv, metadata.json, README.md
Parquet (opcional) e gerado se pyarrow estiver instalado.

Determinismo: cada arquivo usa um RandomState derivado de uma semente base
(registrada em metadata.json), permitindo reproducao exata.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attacks.scenarios import CENARIOS, codigo_para_id  # noqa: E402

#: Proporcao do dataset: 50% legitimo e 12,5% por cenario de ataque.
N_LEGITIMO = 250_000
N_ATAQUE_POR_CENARIO = 62_500
TOTAL = N_LEGITIMO + 4 * N_ATAQUE_POR_CENARIO

DESTINO_PADRAO = ROOT / "data" / "ipv6eh"

#: Flow Label: 20 bits (RFC 8200) -> max 2^20 - 1.
FLOW_LABEL_MAX = 2**20 - 1

#: Versao do protocolo MFA (protocol/mfa_option.VERSION).
VERSAO_EH = 1

GEOHASHES = ["6gyw", "6gyt", "6gzb", "6gzc", "6gzh", "6gz0", "6gzv", "7h3s", "7h3u", "9xq0", "9xq1"]
GEOHASHES_DISTANTES = ["k3sr", "u4pb", "s3xx", "w21u", "2egh", "v75n"]  # exterior
DISPOSITIVOS = ["laptop", "smartphone", "tablet", "desktop", "servidor"]

COLUNAS = (
    ["hora_dia"]
    + [f"dia_{d}" for d in ("seg", "ter", "qua", "qui", "sex", "sab", "dom")]
    + ["localizacao"]
    + [f"disp_{d}" for d in DISPOSITIVOS]
    + ["hist_autent", "taxa_erro", "pacotes_s", "flow_label", "versao_eh", "confianca_fator", "rotulo"]
)

_PADRAO_UM = [1, 0, 0, 0, 0, 0, 0]
_PADRAO_ZERO7 = [0, 0, 0, 0, 0, 0, 0]
_PADRAO_ZERO5 = [0, 0, 0, 0, 0]


def _seno_hora(hora: float) -> float:
    return round(math.sin(2.0 * math.pi * hora / 24.0), 6)


def _onehot(ix: int, n: int) -> list:
    v = [0] * n
    v[ix] = 1
    return v


def _perfil_legitimo(rng) -> dict:
    """Perfil de uma sessao legitima (usuario real, trabalho 8-22 h, dia util)."""
    hora_inicio = rng.uniform(8.0, 22.0)
    dias = [0, 1, 2, 3, 4, 4, 4, 5, 6]
    dia = int(rng.choice(dias))
    geohash = str(rng.choice(GEOHASHES[:5])) if rng.random() < 0.9 else str(rng.choice(GEOHASHES))
    dispositivo = int(rng.choice([0, 0, 0, 1, 1, 2]))  # laptop/smartphone dominantes
    return {"hora": hora_inicio, "dia": dia, "geo": geohash, "disp": dispositivo}


def _evento_legitimo(rng, perfil: dict, hist: int) -> list:
    hora = max(0.0, min(23.99, perfil["hora"]))
    conf = rng.uniform(80.0, 99.0)
    taxa = max(0.0, rng.gamma(1.2, 0.9))
    pacotes = rng.normal(150.0, 25.0)
    return [
        _seno_hora(hora),
        *_onehot(perfil["dia"], 7),
        perfil["geo"],
        *_onehot(perfil["disp"], 5),
        int(hist),
        round(taxa, 3),
        round(max(10.0, pacotes), 1),
        int(rng.randint(0, FLOW_LABEL_MAX + 1)),
        VERSAO_EH,
        round(conf, 3),
    ]


def _evento_c1(rng, perfil: dict, hist: int) -> list:
    """Roubo de credenciais: geolocalizacao atipica, confianca e taxa de erro ruins."""
    hora = max(0.0, min(23.99, perfil["hora"]))
    conf = rng.uniform(30.0, 60.0)
    taxa = rng.uniform(5.0, 25.0)
    geo = str(rng.choice(GEOHASHES_DISTANTES)) if rng.random() < 0.8 else perfil["geo"]
    disp = int(rng.choice([1, 1, 3, 4]))  # dispositivo incomum
    return [
        _seno_hora(hora),
        *_onehot(perfil["dia"], 7),
        geo,
        *_onehot(disp, 5),
        int(hist),
        round(taxa, 3),
        round(rng.normal(140.0, 30.0), 1),
        int(rng.randint(0, FLOW_LABEL_MAX + 1)),
        VERSAO_EH,
        round(conf, 3),
    ]


def _evento_c2(rng, perfil: dict, hist: int, pico: bool) -> list:
    """MITM na comunicacao AM-AD: picos de pacotes_s (violacao de SA / replay IKE)."""
    hora = max(0.0, min(23.99, perfil["hora"]))
    conf = rng.uniform(50.0, 80.0)
    pacotes = rng.uniform(400.0, 2000.0) if pico else rng.normal(150.0, 25.0)
    return [
        _seno_hora(hora),
        *_onehot(perfil["dia"], 7),
        perfil["geo"],
        *_onehot(perfil["disp"], 5),
        int(hist),
        round(rng.uniform(0.0, 8.0), 3),
        round(max(10.0, pacotes), 1),
        int(rng.randint(0, FLOW_LABEL_MAX + 1)),
        VERSAO_EH,
        round(conf, 3),
    ]


def _evento_c3(rng, perfil: dict, hist: int, pacotes_antigos: float) -> list:
    """Replay: metadados MFA antigos (24 h), confianca moderada, rajada reenviada."""
    hora = max(0.0, min(23.99, perfil["hora"]))
    conf = rng.uniform(60.0, 90.0)
    return [
        _seno_hora(hora),
        *_onehot(perfil["dia"], 7),
        perfil["geo"],
        *_onehot(perfil["disp"], 5),
        int(hist),
        round(rng.uniform(0.0, 5.0), 3),
        round(pacotes_antigos, 1),
        int(rng.randint(0, FLOW_LABEL_MAX + 1)),
        VERSAO_EH,
        round(conf, 3),
    ]


def _evento_c4(rng, perfil: dict, hist: int, drift: float) -> list:
    """Spoofing de agente: confianca erratica, reputacao caindo, local/device variando."""
    hora = max(0.0, min(23.99, perfil["hora"]))
    conf = rng.uniform(10.0, 99.0)
    geo = str(rng.choice(GEOHASHES + GEOHASHES_DISTANTES))
    disp = int(rng.randint(0, 5))
    taxa = drift + rng.uniform(0.0, 5.0)
    return [
        _seno_hora(hora),
        *_onehot(int(rng.randint(0, 7)), 7),
        geo,
        *_onehot(disp, 5),
        int(hist),
        round(max(0.0, taxa), 3),
        round(rng.normal(150.0, 30.0), 1),
        int(rng.randint(0, FLOW_LABEL_MAX + 1)),
        VERSAO_EH,
        round(conf, 3),
    ]


_GERADORES = {
    1: _evento_c1,
    2: _evento_c2,
    3: _evento_c3,
    4: _evento_c4,
}


def _gerar(n: int, seed: int, codigo: int) -> list:
    """Gera n eventos do codigo (0=legitimo; 1-4=cenarios). Retorna lista de linhas."""
    rng = np.random.RandomState(seed)
    linhas = []
    sessao = 0
    hist = 0
    while len(linhas) < n:
        sessao += 1
        perfil = _perfil_legitimo(rng)
        tam = int(min(n - len(linhas), rng.poisson(40) + 1))
        pico_c2 = False
        contador_pico = 0
        pacotes_antigos = float(rng.normal(150.0, 25.0))
        for _ in range(tam):
            hist = max(0, min(15, hist + int(rng.choice([-1, 0, 0, 1]))))
            if codigo == 0:
                linha = _evento_legitimo(rng, perfil, hist)
            elif codigo == 1:
                linha = _evento_c1(rng, perfil, hist)
            elif codigo == 2:
                if contador_pico <= 0:
                    pico_c2 = rng.random() < 0.15
                    contador_pico = int(rng.randint(5, 25)) if pico_c2 else 0
                linha = _evento_c2(rng, perfil, hist, pico_c2)
                contador_pico -= 1
            elif codigo == 3:
                pacotes_antigos = float(rng.normal(150.0, 25.0)) if rng.random() < 0.1 else pacotes_antigos
                linha = _evento_c3(rng, perfil, hist, pacotes_antigos)
            elif codigo == 4:
                drift = float(sessao % 20) * 0.5  # reputacao cai ao longo das sessoes
                linha = _evento_c4(rng, perfil, hist, drift)
            else:
                raise ValueError(codigo)
            linha = linha + [codigo]
            linhas.append(linha)
            perfil["hora"] = perfil["hora"] + rng.normal(0.0, 0.05)
    return linhas


def _escrever_csv(caminho: Path, linhas: list) -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        esc = csv.writer(fh, lineterminator="\n")
        esc.writerow(COLUNAS)
        esc.writerows(linhas)


def _escrever_parquet(caminho: Path, linhas: list) -> None:
    try:
        import pandas as pd

        df = pd.DataFrame(linhas, columns=COLUNAS)
        df.to_parquet(caminho, index=False)
        return True
    except ImportError:
        return False


def gerar_dataset(
    destino: Path = DESTINO_PADRAO,
    *,
    n_legitimo: int = N_LEGITIMO,
    n_ataque: int = N_ATAQUE_POR_CENARIO,
    seed: int = 42,
) -> dict:
    """Gera o dataset completo (Anexo B.3) e retorna o resumo dos arquivos."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    resumo = {}
    n_total = n_legitimo + 4 * n_ataque

    arquivos = {"legitimo": 0}
    for codigo in (1, 2, 3, 4):
        arquivos[f"c{codigo}"] = codigo

    metadados = {
        "nome": "IPv6-EH - Autenticacao continua sobre cabecalhos IPv6 (Anexo B)",
        "versao": "1.0",
        "total_eventos": n_total,
        "classes": {
            "0": {"arquivo": "legitimo.csv", "eventos": n_legitimo, "descricao": "legitimo"},
            "1": {"arquivo": "c1.csv", "eventos": n_ataque, "descricao": "C1 - Roubo de Credenciais"},
            "2": {"arquivo": "c2.csv", "eventos": n_ataque, "descricao": "C2 - Man-in-the-Middle"},
            "3": {"arquivo": "c3.csv", "eventos": n_ataque, "descricao": "C3 - Replay de Autenticacao"},
            "4": {"arquivo": "c4.csv", "eventos": n_ataque, "descricao": "C4 - Spoofing de Agente"},
        },
        "features": [c for c in COLUNAS if c != "rotulo"],
        "sementes": {},
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "seed_base": seed,
        "fonte": "Anexo B da tese - Sistema Multiagente Inteligente para Autenticacao Continua e Adaptativa (UNESP)",
    }

    for nome, codigo in arquivos.items():
        n = n_legitimo if codigo == 0 else n_ataque
        semente = seed + codigo
        metadados["sementes"][nome] = semente
        linhas = _gerar(n, semente, codigo)
        _escrever_csv(destino / f"{nome}.csv", linhas)
        ok = _escrever_parquet(destino / f"{nome}.parquet", linhas) if codigo != 0 else _escrever_parquet(destino / f"{nome}.parquet", linhas)
        resumo[nome] = {"linhas": len(linhas), "parquet": ok}

    with open(destino / "metadata.json", "w", encoding="utf-8") as fh:
        json.dump(metadados, fh, ensure_ascii=False, indent=2)

    _escrever_readme(destino)
    return resumo


def _escrever_readme(destino: Path) -> None:
    conteudo = """# IPv6-EH - Dataset de autenticacao continua (Anexo B)

Dataset simulado de autenticacao continua baseada em cabecalhos IPv6 (opcao
TLV 0x1E em Destination Options) e IPSec, gerado no ambiente experimental da
tese. ~500.000 eventos com 10 features contextuais e o rotulo da classe.

## Rotulos
- 0 = legitimo
- 1 = C1 - Roubo de Credenciais (phishing)
- 2 = C2 - Man-in-the-Middle (AM-AD)
- 3 = C3 - Replay de Autenticacao (nonce/timestamp)
- 4 = C4 - Spoofing de Agente (Beta Reputation / X.509)

## Features (Anexo B.2)
hora_dia (seno da hora 0-23), dia_seg..dia_dom (7 one-hot), localizacao
(geohash de 4 caracteres), disp_laptop..disp_servidor (5 one-hot),
hist_autent (autenticacoes nos ultimos 60 min), taxa_erro (%),
pacotes_s (pps no fluxo IPv6), flow_label (20 bits, indice de sessao),
versao_eh, confianca_fator (0-100%).

## Arquivos
- legitimo.csv / c1.csv .. c4.csv (CSV UTF-8, com cabecalho)
- *.parquet (colunar, se pyarrow disponivel)
- metadata.json (sementes e parametrizacao)
- README.md

## Reproducao
```
python -m attacks.generate_dataset
```
Gerado de forma deterministica a partir da semente em metadata.json.

## Protocolo de benchmark (Anexo B.4)
- Normalizar features numericas e one-hot nas categoricas; divisao temporal
  sem vazamento futuro.
- Metricas: TPR, FPR, Precisao, Recall, F1, AUC-ROC; latencia P95; consumo.
- Drift: divisao em janelas temporais (FTRL, ARF, DQN).
- Estatistica: Friedman + Nemenyi sobre 30 repeticoes.

## Privacidade (Anexo B.5)
Sem dados brutos individuais; apenas estatisticas agregadas e anonimizadas.
Conformidade com a LGPD (13.709/2018) e RFC 6973.

## Citacao sugerida
E. A. Moraes; K. A. P. Costa. "IPv6-EH: continuous authentication dataset".
Repositorio LARS/UNESP (publicacao prevista).
"""
    (destino / "README.md").write_text(conteudo, encoding="utf-8")


NUMERICAS = [
    "hora_dia",
    "dia_seg", "dia_ter", "dia_qua", "dia_qui", "dia_sex", "dia_sab", "dia_dom",
    "disp_laptop", "disp_smartphone", "disp_tablet", "disp_desktop", "disp_servidor",
    "hist_autent", "taxa_erro", "pacotes_s", "flow_label", "versao_eh", "confianca_fator",
]


def _carregar_amostra(arquivo: Path, limite: int, rng, rotulo_alvo: str) -> tuple:
    feats, labels = [], []
    with open(arquivo, newline="", encoding="utf-8") as fh:
        leitor = csv.DictReader(fh)
        for i, linha in enumerate(leitor):
            if i >= limite:
                break
            if rng.random() > 0.5:
                continue
            x = {k: float(linha[k]) for k in NUMERICAS}
            feats.append(x)
            labels.append(1 if linha["rotulo"] == rotulo_alvo else 0)
    return feats, labels


def _padronizar(lista, media: dict, desvio: dict) -> list:
    return [{k: (v - media[k]) / desvio[k] for k, v in x.items()} for x in lista]


def checar_separabilidade(destino: Path = DESTINO_PADRAO) -> dict:
    """Checagem de sanidade: FTRL binario legitimo x cada cenario (features
    normalizadas via z-score do treino, conforme Anexo B.4). Retorna AUC por
    cenario; AUC ~0.5 indicaria dataset sem sinal."""
    from eval.metrics import resumo
    from ml.models import FTRLModel

    destino = Path(destino)
    resultado = {}
    for cod, arquivo in [(1, "c1.csv"), (2, "c2.csv"), (3, "c3.csv"), (4, "c4.csv")]:
        rng = np.random.RandomState(cod)
        pos, _ = _carregar_amostra(destino / arquivo, 60000, rng, str(cod))
        neg, _ = _carregar_amostra(destino / "legitimo.csv", 300000, rng, "0")
        n = min(len(pos), len(neg))
        pos, neg = pos[:n], neg[:n]
        treino = pos[: n // 2] + neg[: n // 2]
        media = {k: float(np.mean([x[k] for x in treino])) for k in NUMERICAS}
        desvio = {k: float(np.std([x[k] for x in treino]) or 1.0) for k in NUMERICAS}
        pos, neg = _padronizar(pos, media, desvio), _padronizar(neg, media, desvio)
        modelo = FTRLModel()
        for x in pos[: n // 2]:
            modelo.learn_one(x, 1)
        for x in neg[: n // 2]:
            modelo.learn_one(x, 0)
        scores, labels = [], []
        for x in pos[n // 2 :]:
            scores.append(modelo.predict_proba_one(x).get(1, 0.5))
            labels.append(1)
        for x in neg[n // 2 :]:
            scores.append(modelo.predict_proba_one(x).get(1, 0.5))
            labels.append(0)
        resultado[f"C{cod}"] = resumo(scores, labels)
    return resultado


def validar(destino: Path = DESTINO_PADRAO) -> dict:
    """Checagens de sanidade: contagens, NaNs e balanceamento de rotulos."""
    import io

    total = 0
    na_contagem = 0
    rotulos = {}
    for arquivo in sorted(destino.glob("*.csv")):
        with open(arquivo, newline="", encoding="utf-8") as fh:
            leitor = csv.DictReader(fh)
            for linha in leitor:
                total += 1
                rotulos[linha["rotulo"]] = rotulos.get(linha["rotulo"], 0) + 1
                for chave, valor in linha.items():
                    if chave == "localizacao":
                        continue
                    try:
                        float(valor)
                    except ValueError:
                        na_contagem += 1
    return {"total": total, "por_rotulo": rotulos, "nao_numerico": na_contagem}


if __name__ == "__main__":
    resumo = gerar_dataset()
    checagem = validar()
    print(f"Dataset gerado em {DESTINO_PADRAO}")
    for nome, info in resumo.items():
        print(f"  {nome}.csv: {info['linhas']} linhas (parquet: {info['parquet']})")
    print(f"Total: {checagem['total']} eventos | por rotulo: {checagem['por_rotulo']}")
    print(f"Valores nao numericos: {checagem['nao_numerico']}")
    print("\nSeparabilidade (FTRL, features normalizadas):")
    for cenario, met in checar_separabilidade().items():
        print(f"  {cenario}: AUC={met['auc']:.4f} EER={met['eer']:.4f} TPR@FPR3%={met['tpr_fpr3']:.4f}")

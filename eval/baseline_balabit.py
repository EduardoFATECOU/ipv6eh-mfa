"""Baseline academico com o dataset Balabit Mouse Dynamics Challenge.

Protocolo:
  - 10 usuarios; sessoes brutas (timestamp, x, y) no subdir training_files
    sao genuinas; as sessoes em test_files sao rotuladas em public_labels.csv
    (is_illegal: 1 = impostor, 0 = legitimo);
  - para cada usuario: extrai features por sessao (velocidade, aceleracao,
    distancia, duracao), treina FTRL/ARF com as sessoes genuinas do usuario
    (classe 1) e as genuinas dos demais (classe 0) e testa nas sessoes do
    proprio usuario (legitimas x ilegais);
  - metricas por usuario: EER, AUC, TPR com FPR <= 3% (criterio do QP4).

Fonte: Fulop et al. (2016), 'Balabit Mouse Dynamics Challenge data set'.
Licenca: uso academico (https://github.com/balabit/Mouse-Dynamics-Challenge)
"""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.metrics import resumo  # noqa: E402
from ml.models import ARFModel, FTRLModel, featurize  # noqa: E402

DATA = ROOT / "data" / "balabit" / "Mouse-Dynamics-Challenge-master"
RESULTADOS = ROOT / "eval" / "results"


def _ler_sessao(caminho: Path) -> list:
    """Le uma sessao bruta e retorna lista de (t, x, y)."""
    pontos = []
    with open(caminho, newline="", encoding="utf-8") as fh:
        for linha in fh:
            if not linha.strip() or linha.startswith("record timestamp"):
                continue
            partes = linha.strip().split(",")
            if len(partes) < 6:
                continue
            try:
                t = float(partes[0])
                x = float(partes[4])
                y = float(partes[5])
            except ValueError:
                continue
            pontos.append((t, x, y))
    return pontos


def extrair_features(caminho: Path) -> list:
    """Converte uma sessao bruta em ~12 features agregadas."""
    pts = _ler_sessao(caminho)
    if len(pts) < 3:
        return []
    ts = np.asarray([p[0] for p in pts], dtype=np.float64)
    xs = np.asarray([p[1] for p in pts], dtype=np.float64)
    ys = np.asarray([p[2] for p in pts], dtype=np.float64)

    dt = np.diff(ts)
    dt = np.where(dt <= 1e-6, 1e-6, dt)
    vx = np.diff(xs) / dt
    vy = np.diff(ys) / dt
    vel = np.hypot(vx, vy)

    dvel = np.diff(vel)
    ddt = np.diff(ts[1:])
    ddt = np.where(ddt <= 1e-6, 1e-6, ddt)
    acc = dvel / ddt

    def agg(a):
        return [
            float(np.mean(a)),
            float(np.std(a)),
            float(np.min(a)),
            float(np.max(a)),
        ]

    dist = float(np.sum(np.hypot(np.diff(xs), np.diff(ys))))
    dur = float(ts[-1] - ts[0]) if ts[-1] > ts[0] else 0.0
    return agg(vel) + agg(acc) + agg(vx) + agg(vy) + [dist, dur]


def padronizar(treino: dict, teste: dict, clip: float = 5.0) -> tuple:
    """Z-score com media/desvio do treino; clipping em [-clip, clip].

    As features brutas de mouse chegam a 1e12-1e15 (dt em microssegundos);
    sem padronizacao o FTRL satura. Estatisticas apenas do treino evitam
    vazamento de informacao do teste.
    """
    todas = [f for sess in treino.values() for f in sess]
    arr = np.asarray(todas, dtype=np.float64)
    media = arr.mean(axis=0)
    desvio = arr.std(axis=0)
    desvio = np.where(desvio < 1e-9, 1.0, desvio)

    def _transformar(conj: dict, com_rotulo: bool) -> dict:
        novo = {}
        for user, lista in conj.items():
            arr = np.asarray(
                [e[0] if com_rotulo else e for e in lista], dtype=np.float64
            )
            arr = (arr - media) / desvio
            arr = np.clip(arr, -clip, clip)
            novo[user] = [
                (list(v), e[1]) if com_rotulo else list(v)
                for v, e in zip(arr, lista)
            ]
        return novo

    return _transformar(treino, False), _transformar(teste, True)


def carregar_sessoes() -> tuple:
    """Retorna {user: [(features, rotulo_legitimo)]} para treino e teste."""
    treino = {}
    for pasta in sorted((DATA / "training_files").iterdir()):
        if not pasta.is_dir():
            continue
        treino[pasta.name] = []
        for arq in sorted(pasta.glob("*")):
            feats = extrair_features(arq)
            if feats:
                treino[pasta.name].append(feats)

    rotulos = {}
    with open(DATA / "public_labels.csv", newline="", encoding="utf-8") as fh:
        for linha in csv.DictReader(fh):
            rotulos[linha["filename"]] = int(linha["is_illegal"])

    teste = {}
    for pasta in sorted((DATA / "test_files").iterdir()):
        if not pasta.is_dir():
            continue
        teste[pasta.name] = []
        for arq in sorted(pasta.glob("*")):
            feats = extrair_features(arq)
            if not feats:
                continue
            rotulo = rotulos.get(arq.name)
            if rotulo is None:
                continue
            teste[pasta.name].append((feats, rotulo))
    return treino, teste


def construir_modelo(nome: str, seed: int):
    if nome == "ftrl":
        return FTRLModel(alpha=0.05, beta=1.0)
    if nome == "arf":
        return ARFModel(n_models=10, max_depth=10, lambda_value=10)
    raise ValueError(nome)


def avaliar_usuario(treino: dict, teste: dict, alvo: str, nome: str, seed: int) -> dict:
    pos = treino[alvo]
    neg = [f for u, sess in treino.items() if u != alvo for f in sess]
    rng = np.random.default_rng(seed)
    neg = rng.choice(neg, size=len(pos), replace=False) if neg else []

    modelo = construir_modelo(nome, seed)
    for feats in pos:
        modelo.learn_one(featurize(feats), 1)
    for feats in neg:
        modelo.learn_one(featurize(feats), 0)

    scores, labels = [], []
    for feats, rotulo in teste[alvo]:
        scores.append(modelo.predict_proba_one(featurize(feats)).get(1, 0.5))
        labels.append(1 if rotulo == 0 else 0)
    return resumo(scores, labels)


def executar(modelo: str, seed: int = 42) -> list:
    treino_raw, teste_raw = carregar_sessoes()
    treino, teste = padronizar(treino_raw, teste_raw)
    linhas = []
    for alvo in sorted(teste):
        m = avaliar_usuario(treino, teste, alvo, modelo, seed)
        linhas.append({"usuario": alvo, **{k: round(v, 4) for k, v in m.items()}})
    return linhas


def main() -> None:
    RESULTADOS.mkdir(exist_ok=True)
    for modelo in ("ftrl", "arf"):
        linhas = executar(modelo)
        saida = RESULTADOS / f"balabit_{modelo}.csv"
        with open(saida, "w", newline="", encoding="utf-8") as fh:
            campo = ["usuario", "auc", "eer", "tpr_fpr3", "n_pos", "n_neg"]
            esc = csv.DictWriter(fh, fieldnames=campo)
            esc.writeheader()
            esc.writerows(linhas)
        aucs = [l["auc"] for l in linhas]
        eers = [l["eer"] for l in linhas]
        tprs = [l["tpr_fpr3"] for l in linhas]
        print(f"== Balabit Mouse Dynamics - {modelo.upper()} ==")
        print(f"  AUC:  media={np.mean(aucs):.4f} +- {np.std(aucs):.4f}")
        print(f"  EER:  media={np.mean(eers):.4f} +- {np.std(eers):.4f}")
        print(f"  TPR@FPR<=3%: media={np.mean(tprs):.4f} +- {np.std(tprs):.4f}")
        print(f"  -> {saida}\n")


if __name__ == "__main__":
    main()

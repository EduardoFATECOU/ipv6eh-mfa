"""Simulacao local da campanha experimental C1-C4 (Cap. 7 -> Cap. 8).

Reexecuta, em um unico host, a avaliacao da autenticacao continua sobre o
dataset proprio IPv6-EH (Anexo B), implementando o protocolo de benchmark
do Anexo B.4:

  - fluxo temporal deterministico com sessoes legitimas intercaladas por
    episodios de ataque (C1-C4), reconstruido por semente;
  - aquecimento (warm-up) apenas com eventos legitimso para normalizacao
    z-score sem vazamento futuro;
  - aprendizado incremental estrito: prever -> medir -> aprender;
  - deteccao de drift (ADWIN sobre o fluxo de erros) e acuracia por janelas
    temporais;
  - latencia do protocolo 0x1E (build/parse/empacotamento Scapy) e de
    inferencia de cada modelo (P50/P95/P99).

Modelos (Tabelas 8.x): FTRL-Proximal, ARF(ADWIN), Ensemble (media) como
detectores, e a DQN (politica do Agente Decisor, estado de 10 dimensoes e 3
acoes) com metricas operacionais. A comparacao estatistica sobre as
repeticoes usa Friedman + Nemenyi (eval/stats.py).

Uso (campanha reduzida para validacao):
    python -m eval.simulador --reps 3 --eventos 12000 --warm 1000

Uso (campanha final da tese, 30 repeticoes):
    python -m eval.simulador --reps 30 --eventos 20000 --warm 2000

Saidas em eval/results/:
  simulacao_det.csv  (uma linha por repeticao x modelo x cenario)
  simulacao_dqn.csv  (politica do Agente Decisor por repeticao x cenario)
  simulacao_drift.csv (acuracia por janela temporal, por repeticao x modelo)
  SIMULACAO.md      (tabelas consolidadas com Friedman/Nemenyi)
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attacks.generate_dataset import GEOHASHES_DISTANTES, GEOHASHES  # noqa: E402
from eval.metrics import resumo  # noqa: E402
from eval.stats import comparar  # noqa: E402
from ml.dqn import DQNAgent  # noqa: E402
from ml.models import ARFModel, EnsembleModel, FTRLModel, featurize  # noqa: E402

DESTINO = ROOT / "data" / "ipv6eh"
RESULTADOS = ROOT / "eval" / "results"

#: Geohashes na ordem fixa das features (11 locais + 6 externos).
GEOHASHES_ORD = list(GEOHASHES) + list(GEOHASHES_DISTANTES)

#: Features numericas (6) + one-hot dia (7) + one-hot dispositivo (5) + geohash (17).
FEATS = (
    ["hora_dia", "hist_autent", "taxa_erro", "pacotes_s", "flow_label", "confianca_fator"]
    + [f"dia_{d}" for d in ("seg", "ter", "qua", "qui", "sex", "sab", "dom")]
    + [f"disp_{d}" for d in ("laptop", "smartphone", "tablet", "desktop", "servidor")]
    + list(GEOHASHES_ORD)
)

DIAS = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")
DISPOSITIVOS = ("laptop", "smartphone", "tablet", "desktop", "servidor")

#: Indices dentro de FEATS.
IDX_CONT = np.arange(6)
IDX_DIA = 6
IDX_DISP = 13
IDX_GEO = 18
IDX_GEO_EXTERNO = slice(18 + len(GEOHASHES), 18 + len(GEOHASHES_ORD))

ARQUIVOS = [(0, "legitimo"), (1, "c1"), (2, "c2"), (3, "c3"), (4, "c4")]

MODELOS_DETECTORES = ("ftrl", "arf", "ensemble")

#: Janela temporal da avaliacao de drift (Anexo B.4).
JANELA = 5000
#: Recompensas da politica do Agente Decisor (assimetricas, fail-secure).
#: formato: (legitimo, ataque) para cada acao [permitir, desafiar, bloquear].
RECOMPENSAS = {0: (1.0, -5.0), 1: (-0.3, -0.3), 2: (-2.0, 2.0)}


def _carregar_arquivo(arquivo: Path) -> np.ndarray:
    """Le um CSV do dataset e devolve a matriz de features (n, len(FEATS))."""
    linhas = []
    with open(arquivo, newline="", encoding="utf-8") as fh:
        for linha in csv.DictReader(fh):
            row = np.zeros(len(FEATS))
            row[0] = float(linha["hora_dia"])
            row[1] = float(linha["hist_autent"])
            row[2] = float(linha["taxa_erro"])
            row[3] = float(linha["pacotes_s"])
            row[4] = float(linha["flow_label"])
            row[5] = float(linha["confianca_fator"])
            for j, d in enumerate(DIAS):
                row[IDX_DIA + j] = float(linha[f"dia_{d}"])
            for j, d in enumerate(DISPOSITIVOS):
                row[IDX_DISP + j] = float(linha[f"disp_{d}"])
            geo = linha["localizacao"]
            if geo in GEOHASHES_ORD:
                row[IDX_GEO + GEOHASHES_ORD.index(geo)] = 1.0
            else:
                row[IDX_GEO] = 1.0
            linhas.append(row)
    return np.asarray(linhas, dtype=np.float64)


def carregar_classes(destino: Path = DESTINO) -> dict:
    """Carrega as cinco classes do dataset em um dicionario codigo -> matriz."""
    classes = {}
    for codigo, nome in ARQUIVOS:
        arquivo = destino / f"{nome}.csv"
        if not arquivo.exists():
            raise FileNotFoundError(
                f"{arquivo} nao existe. Gere o dataset com: python -m attacks.generate_dataset"
            )
        classes[codigo] = _carregar_arquivo(arquivo)
    return classes


def montar_stream(classes: dict, n_total: int, warm: int, seed: int) -> tuple:
    """Constroi o fluxo temporal deterministico (sessoes legitimas + ataques).

    Os primeiros ``warm`` eventos sao legitimso (usados no aquecimento e na
    normalizacao). Em seguida cada sessao e legitima (70%) ou um episodio de
    ataque C1-C4 (30%), com comprimento Poisson(40)+1. Retorna (X, y) com y
    em {0..4} (0 = legitimo).
    """
    rng = np.random.RandomState(seed)
    perm = {cod: rng.permutation(len(cls)) for cod, cls in classes.items()}
    ptr = {cod: 0 for cod in classes}
    Xs, ys = [], []

    warm_real = min(warm, len(classes[0]))
    Xs.append(classes[0][perm[0][:warm_real]])
    ys.append(np.zeros(warm_real, dtype=np.int64))
    ptr[0] = warm_real

    while sum(len(a) for a in Xs) < n_total:
        restante = n_total - sum(len(a) for a in Xs)
        if restante <= 0:
            break
        cod = 0 if rng.random() < 0.70 else int(rng.randint(1, 5))
        if ptr[cod] >= len(classes[cod]):
            candidatos = [c for c in classes if ptr[c] < len(classes[c])]
            if not candidatos:
                break
            cod = int(rng.choice(candidatos))
        comprimento = int(rng.poisson(40) + 1)
        comprimento = min(comprimento, len(classes[cod]) - ptr[cod], restante)
        if comprimento <= 0:
            break
        Xs.append(classes[cod][perm[cod][ptr[cod]: ptr[cod] + comprimento]])
        ys.append(np.full(comprimento, cod, dtype=np.int64))
        ptr[cod] += comprimento

    X = np.concatenate(Xs)[:n_total]
    y = np.concatenate(ys)[:n_total]
    return X, y


def _estatisticas(X: np.ndarray, warm: int) -> tuple:
    """Media e desvio das 6 features continuas no aquecimento (so legitimas)."""
    med = X[:warm, IDX_CONT].mean(axis=0)
    des = X[:warm, IDX_CONT].std(axis=0)
    des[des == 0.0] = 1.0
    return med, des


def _padronizar(X: np.ndarray, med: np.ndarray, des: np.ndarray) -> np.ndarray:
    X = X.copy()
    X[:, IDX_CONT] = (X[:, IDX_CONT] - med) / des
    return X


def _construir_detector(nome: str, seed: int):
    if nome == "ftrl":
        return FTRLModel()
    if nome == "arf":
        return ARFModel(seed=seed)
    if nome == "ensemble":
        return EnsembleModel([FTRLModel(), ARFModel(seed=seed)])
    raise ValueError(f"detector desconhecido: {nome}")


def avaliar_detector(X: np.ndarray, y: np.ndarray, nome: str, warm: int, seed: int) -> dict:
    """Prever -> medir -> aprender sobre o fluxo. Retorna scores, rotulos e drift."""
    modelo = _construir_detector(nome, seed)
    from river.drift import ADWIN

    adwin = ADWIN()
    n = len(y)
    scores = np.empty(n - warm, dtype=np.float64)
    ybin = np.empty(n - warm, dtype=np.int64)
    cen = np.empty(n - warm, dtype=np.int64)
    lat = []
    janelas = []
    certas = 0
    drift = 0

    for i in range(warm):
        modelo.learn_one(featurize(X[i], FEATS), int(y[i] != 0))

    for j, i in enumerate(range(warm, n)):
        xi = featurize(X[i], FEATS)
        amostra_lat = (j % 50) == 0
        t0 = time.perf_counter_ns() if amostra_lat else None
        s = modelo.predict_proba_one(xi).get(1, 0.5)
        if t0 is not None:
            lat.append(time.perf_counter_ns() - t0)
        yt = int(y[i] != 0)
        scores[j], ybin[j], cen[j] = s, yt, int(y[i])
        erro = float(int(s >= 0.5) != yt)
        certas += int(erro == 0.0)
        adwin.update(erro)
        if adwin.drift_detected:
            drift += 1
        modelo.learn_one(xi, yt)
        if (j + 1) % JANELA == 0:
            janelas.append((j + 1, certas / (j + 1)))

    p50, p95, p99 = _percentis(lat)
    return {
        "scores": scores,
        "ybin": ybin,
        "cenario": cen,
        "drift": drift,
        "lat_p50_us": p50,
        "lat_p95_us": p95,
        "lat_p99_us": p99,
        "janelas": janelas,
    }


def estado_dqn(x: np.ndarray, s_risco: float) -> list:
    """Estado de 10 dimensoes do Agente Decisor (Cap. 7), tudo em [0,1]."""
    return [
        float(s_risco),
        float(min(x[5] / 100.0, 1.0)),
        float(min(x[2] / 25.0, 1.0)),
        float(min(x[3] / 2000.0, 1.0)),
        float(min(x[1] / 15.0, 1.0)),
        float(x[0]),
        float(x[IDX_DISP]),
        float(x[IDX_DISP + 1]),
        float(x[IDX_GEO_EXTERNO].max()),
        float(x[IDX_DISP + 3]),
    ]


def avaliar_dqn(X: np.ndarray, y: np.ndarray, warm: int, seed: int) -> dict:
    """Politica do Agente Decisor: estado 10d, acoes {permitir, desafiar, bloquear}.

    O sinal de risco que alimenta o estado vem de um FTRL vivo (o AD avalia a
    confianca agregada dos fatores). Recompensas assimetricas (fail-secure).
    """
    ftrl = FTRLModel()
    for i in range(warm):
        ftrl.learn_one(featurize(X[i], FEATS), int(y[i] != 0))

    agente = DQNAgent(n_features=10, n_actions=3, seed=seed,
                      gamma=0.0, lr=3e-3, epsilon_decay=0.998)
    n = len(y)
    acoes = np.empty(n - warm, dtype=np.int64)
    scores = np.empty(n - warm, dtype=np.float64)
    lat = []
    for j, i in enumerate(range(warm, n)):
        xi = featurize(X[i], FEATS)
        s = ftrl.predict_proba_one(xi).get(1, 0.5)
        ftrl.learn_one(xi, int(y[i] != 0))
        st = estado_dqn(X[i], s)
        amostra_lat = (j % 50) == 0
        t0 = time.perf_counter_ns() if amostra_lat else None
        a_train = agente.act(st)               # exploracao no treinamento
        a_greedy = agente.act(st, explore=False)  # politica reportada
        if t0 is not None:
            lat.append(time.perf_counter_ns() - t0)
        acoes[j] = a_greedy
        q = agente.net.predict(np.asarray(st, dtype=np.float64))
        scores[j] = float(q[2] - q[0])
        legit = int(y[i]) == 0
        recompensa = RECOMPENSAS[a_train][0] if legit else RECOMPENSAS[a_train][1]
        agente.remember(st, a_train, recompensa, st, False)
        agente.learn()

    p50, p95, p99 = _percentis(lat)
    return {"acoes": acoes, "scores": scores, "ybin": np.array(y[warm:] != 0, dtype=np.int64),
            "cenario": y[warm:].astype(np.int64), "lat_p50_us": p50, "lat_p95_us": p95,
            "lat_p99_us": p99}


def _percentis(lat: list) -> tuple:
    if not lat:
        return 0.0, 0.0, 0.0
    v = np.asarray(lat, dtype=np.float64) / 1e3  # ns -> us
    return (float(np.percentile(v, 50)), float(np.percentile(v, 95)),
            float(np.percentile(v, 99)))


def medir_protocolo(n: int = 2000, seed: int = 42) -> dict:
    """Latencias do protocolo 0x1E (build, parse, pacote Scapy) em microsegundos."""
    from protocol.mfa_option import (
        agent_id_from_key,
        build_option_data,
        extract_option_from_packet,
        make_destopts_packet,
        parse_option_data,
    )

    rng = np.random.default_rng(seed)
    ts_build, ts_parse, ts_pacote = [], [], []
    ts = int(time.time())
    agente = agent_id_from_key("lars/am-1")
    for _ in range(n):
        t0 = time.perf_counter_ns()
        data = build_option_data(3, float(rng.uniform(0, 100)), timestamp=ts,
                                 agent_id=agente, nonce=int(rng.integers(0, 2**32)))
        t1 = time.perf_counter_ns()
        cred = parse_option_data(data)
        t2 = time.perf_counter_ns()
        pacote = make_destopts_packet(data)
        extract_option_from_packet(pacote)
        t3 = time.perf_counter_ns()
        ts_build.append(t1 - t0)
        ts_parse.append(t2 - t1)
        ts_pacote.append(t3 - t2)
        assert cred.nonce >= 0

    return {
        "build_p50_us": float(np.percentile(ts_build, 50)) / 1e3,
        "build_p95_us": float(np.percentile(ts_build, 95)) / 1e3,
        "parse_p50_us": float(np.percentile(ts_parse, 50)) / 1e3,
        "parse_p95_us": float(np.percentile(ts_parse, 95)) / 1e3,
        "pacote_p50_us": float(np.percentile(ts_pacote, 50)) / 1e3,
        "pacote_p95_us": float(np.percentile(ts_pacote, 95)) / 1e3,
    }


def _metricas_por_cenario(scores: np.ndarray, ybin: np.ndarray, cen: np.ndarray) -> dict:
    """Resumo (auc/eer/tpr@fpr3) + ponto de operacao QP4 por cenario e global."""
    from eval.metrics import operating_point

    out = {}
    leg = ybin == 0
    for c in (1, 2, 3, 4):
        ata = cen == c
        if ata.sum() == 0 or leg.sum() == 0:
            continue
        r = resumo(np.concatenate([scores[ata], scores[leg]]),
                   np.concatenate([np.ones(ata.sum(), dtype=np.int64),
                                   np.zeros(leg.sum(), dtype=np.int64)]))
        op = operating_point(np.concatenate([scores[ata], scores[leg]]),
                             np.concatenate([np.ones(ata.sum(), dtype=np.int64),
                                             np.zeros(leg.sum(), dtype=np.int64)]))
        out[f"C{c}"] = {**r, **op}
    r = resumo(scores, ybin)
    op = operating_point(scores, ybin)
    out["GLOBAL"] = {**r, **op}
    return out


def _metricas_politica(acoes: np.ndarray, scores: np.ndarray, ybin: np.ndarray,
                       cen: np.ndarray) -> dict:
    """Metricas operacionais da politica: TPR/FPR, taxas de bloqueio/escalada e AUC."""
    out = {}
    leg = ybin == 0
    ataque = ybin == 1
    detec = (acoes >= 1)  # desafiar ou bloquear conta como resposta nao-permitir
    for c in (1, 2, 3, 4):
        ata = cen == c
        if ata.sum() == 0 or leg.sum() == 0:
            continue
        tpr = float(detec[ata].mean())
        fpr = float(detec[leg].mean())
        bloc = float((acoes == 2).mean())
        esc = float((acoes == 1).mean())
        out[f"C{c}"] = {"tpr_pol": tpr, "fpr_pol": fpr, "taxa_bloqueio": bloc,
                        "taxa_escalada": esc}
    tpr = float(detec[ataque].mean())
    fpr = float(detec[leg].mean())
    auc = resumo(scores, ybin)["auc"]
    out["GLOBAL"] = {"tpr_pol": tpr, "fpr_pol": fpr, "taxa_bloqueio": float((acoes == 2).mean()),
                     "taxa_escalada": float((acoes == 1).mean()), "auc": auc}
    return out


def _escrever_csv(caminho: Path, campo: list, linhas: list) -> None:
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        esc = csv.DictWriter(fh, fieldnames=campo, extrasaction="ignore")
        esc.writeheader()
        esc.writerows(linhas)


def executar(reps: int, n_total: int, warm: int, modelos: list, seed_base: int,
             destino: Path = DESTINO, resultados: Path = RESULTADOS) -> dict:
    """Executa a campanha completa e retorna os resumos por modelo/cenario."""
    classes = carregar_classes(destino)
    linhas_det = []
    linhas_dqn = []
    linhas_drift = []

    for rep in range(reps):
        seed = seed_base + rep
        X, y = montar_stream(classes, n_total, warm, seed)
        med, des = _estatisticas(X, warm)
        X = _padronizar(X, med, des)

        for nome in modelos:
            if nome == "dqn":
                continue
            det = avaliar_detector(X, y, nome, warm, seed)
            por_cenario = _metricas_por_cenario(det["scores"], det["ybin"], det["cenario"])
            for cenario, m in por_cenario.items():
                linhas_det.append({
                    "rep": rep, "modelo": nome, "cenario": cenario,
                    "auc": round(m["auc"], 4), "eer": round(m["eer"], 4),
                    "tpr": round(m["tpr"], 4), "fpr": round(m["fpr"], 4),
                    "precisao": round(m["precisao"], 4), "recall": round(m["recall"], 4),
                    "f1": round(m["f1"], 4), "tpr_fpr3": round(m["tpr_fpr3"], 4),
                    "n_pos": m["n_pos"], "n_neg": m["n_neg"],
                    "drift": det["drift"], "lat_p50_us": round(det["lat_p50_us"], 2),
                    "lat_p95_us": round(det["lat_p95_us"], 2),
                    "lat_p99_us": round(det["lat_p99_us"], 2),
                })
            for fim, acc in det["janelas"]:
                linhas_drift.append({"rep": rep, "modelo": nome, "janela": fim,
                                     "acuracia": round(acc, 4)})

        if "dqn" in modelos:
            pol = avaliar_dqn(X, y, warm, seed)
            por_cenario = _metricas_politica(pol["acoes"], pol["scores"], pol["ybin"],
                                             pol["cenario"])
            for cenario, m in por_cenario.items():
                linha = {"rep": rep, "modelo": "dqn", "cenario": cenario}
                linha.update({k: round(v, 4) for k, v in m.items()})
                linha["lat_p95_us"] = round(pol["lat_p95_us"], 2)
                linhas_dqn.append(linha)

    RESULTADOS = Path(resultados)
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    _escrever_csv(RESULTADOS / "simulacao_det.csv",
                  ["rep", "modelo", "cenario", "auc", "eer", "tpr_fpr3", "tpr", "fpr",
                   "precisao", "recall", "f1", "n_pos", "n_neg",
                   "drift", "lat_p50_us", "lat_p95_us", "lat_p99_us"], linhas_det)
    _escrever_csv(RESULTADOS / "simulacao_dqn.csv",
                  ["rep", "modelo", "cenario", "tpr_pol", "fpr_pol", "taxa_bloqueio",
                   "taxa_escalada", "auc", "lat_p95_us"], linhas_dqn)
    _escrever_csv(RESULTADOS / "simulacao_drift.csv",
                  ["rep", "modelo", "janela", "acuracia"], linhas_drift)
    return {"det": linhas_det, "dqn": linhas_dqn, "drift": linhas_drift}


def _media_std(linhas: list, cenario: str, modelo: str, campo: str) -> tuple:
    v = [float(l[campo]) for l in linhas
         if l["cenario"] == cenario and l["modelo"] == modelo and not np.isnan(float(l[campo]))]
    if not v:
        return float("nan"), float("nan")
    return float(np.mean(v)), float(np.std(v))


def _tabela_detector(linhas: list, modelos: list, cenarios: list) -> str:
    cab = ("| Modelo | AUC | EER | TPR@FPR<=3% | Precisao | F1 | P95 (us) | Drift |\n"
           "|---|---:|---:|---:|---:|---:|---:|---:|\n")
    blocos = []
    for cenario in cenarios:
        lin = f"**{cenario}**\n\n" + cab
        for modelo in modelos:
            auc_m, auc_s = _media_std(linhas, cenario, modelo, "auc")
            eer_m, eer_s = _media_std(linhas, cenario, modelo, "eer")
            tpr_m, tpr_s = _media_std(linhas, cenario, modelo, "tpr_fpr3")
            prec_m, prec_s = _media_std(linhas, cenario, modelo, "precisao")
            f1_m, f1_s = _media_std(linhas, cenario, modelo, "f1")
            p95_m, _ = _media_std(linhas, cenario, modelo, "lat_p95_us")
            drf_m, _ = _media_std(linhas, cenario, modelo, "drift")
            lin += (f"| {modelo.upper()} | {auc_m:.4f} ± {auc_s:.4f} | "
                    f"{eer_m:.4f} ± {eer_s:.4f} | {tpr_m:.4f} ± {tpr_s:.4f} | "
                    f"{prec_m:.4f} ± {prec_s:.4f} | {f1_m:.4f} ± {f1_s:.4f} | "
                    f"{p95_m:.1f} | {drf_m:.1f} |\n")
        blocos.append(lin)
    return "\n\n".join(blocos)


def _tabela_politica(linhas: list, cenarios: list) -> str:
    cab = "| Cenario | TPR | FPR | Taxa bloqueio | Taxa escalada | P95 (us) |\n|---|---:|---:|---:|---:|---:|\n"
    out = cab
    for cenario in cenarios:
        tpr, _ = _media_std(linhas, cenario, "dqn", "tpr_pol")
        fpr, _ = _media_std(linhas, cenario, "dqn", "fpr_pol")
        bloc, _ = _media_std(linhas, cenario, "dqn", "taxa_bloqueio")
        esc, _ = _media_std(linhas, cenario, "dqn", "taxa_escalada")
        p95, _ = _media_std(linhas, cenario, "dqn", "lat_p95_us")
        out += (f"| {cenario} | {tpr:.4f} | {fpr:.4f} | {bloc:.4f} | {esc:.4f} | {p95:.1f} |\n")
    return out


def _tabela_friedman(linhas: list, modelos: list, cenario: str, campo: str) -> str:
    matriz = np.array([[float(l[campo]) for l in linhas
                        if l["cenario"] == cenario and l["modelo"] == m] for m in modelos])
    matriz = np.nan_to_num(matriz, nan=0.0)
    comp = comparar(modelos, matriz)
    out = f"**Friedman/Nemenyi - {cenario} ({campo})**\n\n"
    for m in modelos:
        out += f"- {m.upper()}: rank medio {comp['ranks'][m]:.3f}\n"
    f = comp["friedman"]
    p_chi = f["p_chi2"]
    p_str = f"{p_chi:.4f}" if p_chi is not None else "n/d"
    out += (f"\n- chi2(Friedman) = {f['chi2_friedman']:.3f} "
            f"(critico 0.05 = {f['chi2_crit_05']}) | p = {p_str} -> "
            f"{'rejeita H0' if f['rejeita_nula_05'] else 'nao rejeita H0'}\n")
    out += f"- F (Iman-Davenport) = {f['f_imandavenport']:.3f}\n"
    out += f"- CD (Nemenyi, 0.05) = {comp['nemenyi_cd']:.3f}\n"
    pares = comp["pares_significativos"]
    out += "- pares significativos: " + (", ".join(
        f"{a.upper()}-{b.upper()}" for a, b in pares) if pares else "nenhum") + "\n"
    return out


def gerar_resumo(linhas_det: list, linhas_dqn: list, protocolo: dict,
                 modelos: list, reps: int, n_total: int) -> str:
    """Monta o SIMULACAO.md consolidado (Tabelas 8.x)."""
    cenarios = ["C1", "C2", "C3", "C4", "GLOBAL"]
    partes = [f"# Simulacao local - campanha C1-C4 (Cap. 8)\n",
              f"\n- Fluxo por repeticao: {n_total} eventos; repeticoes: {reps}; "
              f"modelos: {', '.join(m.upper() for m in modelos)}.",
              f"- Protocolo de avaliacao: prever -> medir -> aprender (Anexo B.4); "
              f"normalizacao z-score so no aquecimento (sem vazamento).",
              "\n## Detectores (Tabelas 8.x)\n",
              _tabela_detector(linhas_det, modelos, cenarios),
              "\n## Politica do Agente Decisor (DQN)\n",
              _tabela_politica(linhas_dqn, cenarios),
              "\n## Comparacao estatistica (Friedman + Nemenyi)\n"]
    for cenario in cenarios:
        partes.append(_tabela_friedman(linhas_det, modelos, cenario, "auc"))
    partes.append("\n## Latencia do protocolo 0x1E\n\n")
    partes.append(f"- build: P50 {protocolo['build_p50_us']:.2f} us, "
                  f"P95 {protocolo['build_p95_us']:.2f} us\n")
    partes.append(f"- parse: P50 {protocolo['parse_p50_us']:.2f} us, "
                  f"P95 {protocolo['parse_p95_us']:.2f} us\n")
    partes.append(f"- pacote (Scapy): P50 {protocolo['pacote_p50_us']:.2f} us, "
                  f"P95 {protocolo['pacote_p95_us']:.2f} us\n")
    return "\n".join(partes)


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=10, help="repeticoes (tese: 30)")
    ap.add_argument("--eventos", type=int, default=20000, help="eventos por repeticao")
    ap.add_argument("--warm", type=int, default=2000, help="eventos de aquecimento")
    ap.add_argument("--modelos", default="ftrl,arf,ensemble,dqn",
                    help="modelos separados por virgula")
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--saida", default=str(Path(__file__).resolve().parent / "results"))
    args = ap.parse_args(argv)

    modelos = [m.strip() for m in args.modelos.split(",") if m.strip()]
    resultados_dir = Path(args.saida)
    resultados_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    resultado = executar(args.reps, args.eventos, args.warm, modelos, args.seed_base,
                         resultados=resultados_dir)
    protocolo = medir_protocolo()
    resumo_md = gerar_resumo(resultado["det"], resultado["dqn"], protocolo,
                             [m for m in modelos if m != "dqn"], args.reps, args.eventos)
    (resultados_dir / "SIMULACAO.md").write_text(resumo_md, encoding="utf-8")

    print(f"\nCampanha concluida em {time.time() - t0:.1f}s.")
    print(f"-> {resultados_dir / 'simulacao_det.csv'}")
    print(f"-> {resultados_dir / 'simulacao_dqn.csv'}")
    print(f"-> {resultados_dir / 'simulacao_drift.csv'}")
    print(f"-> {resultados_dir / 'SIMULACAO.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

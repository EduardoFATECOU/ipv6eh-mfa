"""Testes da simulacao local (eval/simulador.py) e estatistica (eval/stats.py)."""

import numpy as np
import pytest

from eval.metrics import resumo
from eval.simulador import (
    FEATS,
    avaliar_detector,
    carregar_classes,
    estado_dqn,
    medir_protocolo,
    montar_stream,
    _estatisticas,
    _metricas_por_cenario,
    _padronizar,
)
from eval.stats import (
    comparar,
    friedman,
    media_ranks,
    nemenyi_cd,
    pares_significativos,
)


def _classes_sinteticas(n_leg=500, n_ataque=80):
    rng = np.random.default_rng(0)
    n = len(FEATS)
    classes = {
        0: rng.normal(0.0, 1.0, (n_leg, n)),
        1: rng.normal(2.0, 1.0, (n_ataque, n)),
        2: rng.normal(3.0, 1.0, (n_ataque, n)),
        3: rng.normal(4.0, 1.0, (n_ataque, n)),
        4: rng.normal(5.0, 1.0, (n_ataque, n)),
    }
    return classes


def test_montar_stream_estrutura():
    classes = _classes_sinteticas()
    X, y = montar_stream(classes, n_total=600, warm=100, seed=1)
    assert X.shape == (600, len(FEATS))
    assert y.shape == (600,)
    assert set(np.unique(y)) <= {0, 1, 2, 3, 4}
    assert (y[:100] == 0).all()  # aquecimento so legitimo
    assert (y == 0).sum() > 0 and (y != 0).sum() > 0


def test_montar_stream_esgota_classes_sem_loop():
    # disponiveis: 500 + 4*80 = 820 < n_total=2000 -> deve parar sem girar.
    classes = _classes_sinteticas()
    X, y = montar_stream(classes, n_total=2000, warm=100, seed=1)
    assert len(X) <= 2000
    assert len(y) == len(X)
    assert (y[:100] == 0).all()


def test_montar_stream_deterministico():
    classes = _classes_sinteticas()
    a = montar_stream(classes, 600, 80, seed=7)
    b = montar_stream(classes, 600, 80, seed=7)
    assert np.array_equal(a[0], b[0])
    assert np.array_equal(a[1], b[1])


def test_padronizacao_aquecimento():
    classes = _classes_sinteticas()
    X, _ = montar_stream(classes, 800, 200, seed=2)
    med, des = _estatisticas(X, 200)
    Xp = _padronizar(X, med, des)
    col0 = Xp[:200, 0]
    assert abs(col0.mean()) < 1e-9
    assert abs(col0.std() - 1.0) < 1e-9


def test_avaliar_detector_estrutura():
    classes = _classes_sinteticas(n_leg=4000, n_ataque=600)
    X, y = montar_stream(classes, 6000, 400, seed=3)
    med, des = _estatisticas(X, 400)
    Xp = _padronizar(X, med, des)
    det = avaliar_detector(Xp, y, "ftrl", 400, seed=3)
    assert det["scores"].shape == (5600,)
    assert det["ybin"].shape == (5600,)
    assert det["cenario"].shape == (5600,)
    assert det["drift"] >= 0
    assert det["lat_p95_us"] >= 0.0
    assert len(det["janelas"]) > 0  # fluxo longo o bastante para janelas


def test_metricas_por_cenario():
    rng = np.random.default_rng(4)
    scores = rng.uniform(0, 1, 600)
    ybin = np.zeros(600, dtype=np.int64)
    cen = np.zeros(600, dtype=np.int64)
    ybin[:400] = 1
    cen[:100], cen[100:200], cen[200:300], cen[300:400] = 1, 2, 3, 4
    out = _metricas_por_cenario(scores, ybin, cen)
    assert set(out) == {"C1", "C2", "C3", "C4", "GLOBAL"}
    assert out["GLOBAL"]["n_pos"] == 400
    assert out["GLOBAL"]["n_neg"] == 200


def test_estado_dqn_10_dims():
    x = np.zeros(len(FEATS))
    x[5], x[2], x[3], x[1], x[0] = 80.0, 10.0, 500.0, 8.0, 0.5
    x[13], x[14], x[16] = 1.0, 0.0, 0.0
    st = estado_dqn(x, 0.9)
    assert len(st) == 10
    assert all(0.0 <= v <= 1.0 for v in st)
    assert st[0] == 0.9 and st[1] == 0.8


def test_medir_protocolo():
    m = medir_protocolo(n=300, seed=5)
    assert m["build_p95_us"] > 0.0
    assert m["parse_p95_us"] > 0.0
    assert m["pacote_p95_us"] > 0.0


def test_media_ranks():
    dados = np.array([[9.0, 8.0, 7.0], [6.0, 5.0, 4.0], [3.0, 2.0, 1.0]])
    r = media_ranks(dados)
    assert np.allclose(r, [1.0, 2.0, 3.0])


def test_friedman_rejeita_nula():
    rng = np.random.default_rng(0)
    base = np.array([9.0, 6.0, 3.0])
    dados = base[:, None] + rng.normal(0, 0.05, (3, 30))
    f = friedman(dados)
    assert f["k"] == 3 and f["n"] == 30
    assert f["rejeita_nula_05"] is True
    assert f["chi2_friedman"] > f["chi2_crit_05"]


def test_nemenyi_cd():
    cd = nemenyi_cd(3, 30)
    assert cd == pytest.approx(2.343 * np.sqrt(12.0 / 180.0))


def test_pares_significativos():
    rng = np.random.default_rng(1)
    base = np.array([9.0, 6.0, 3.0])
    dados = base[:, None] + rng.normal(0, 0.05, (3, 30))
    pares = pares_significativos(dados)
    assert (0, 1) in pares and (1, 2) in pares and (0, 2) in pares


def test_comparar_empacota():
    rng = np.random.default_rng(2)
    dados = np.vstack([rng.normal(9, 0.1, 20), rng.normal(5, 0.1, 20),
                       rng.normal(2, 0.1, 20)])
    comp = comparar(["a", "b", "c"], dados)
    assert comp["ranks"]["a"] < comp["ranks"]["b"] < comp["ranks"]["c"]
    assert comp["friedman"]["rejeita_nula_05"]
    assert comp["nemenyi_cd"] > 0.0

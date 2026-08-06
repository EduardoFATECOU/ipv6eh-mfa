"""Testes do modulo ml/ (FTRL, ARF, DQN) e eval/ (metricas)."""

import numpy as np
import pytest

from eval.metrics import eer, operating_point, roc_auc, resumo, tpr_at_fpr
from ml.dqn import DQNAgent, demo_dqn, synthetic_risk_mdp
from ml.models import ARFModel, EnsembleModel, FTRLModel, featurize


def _stream():
    rng = np.random.default_rng(0)
    for _ in range(300):
        x = featurize([rng.uniform(0, 1), rng.uniform(0, 1)])
        y = 1 if x["f0"] > 0.5 else 0
        yield x, y


def test_ftrl_interface():
    m = FTRLModel()
    for x, y in _stream():
        m.learn_one(x, y)
    assert m.predict_one({"f0": 0.9, "f1": 0.1}) in (0, 1)
    proba = m.predict_proba_one({"f0": 0.9, "f1": 0.1})
    assert set(proba) == {0, 1}
    assert abs(sum(proba.values()) - 1.0) < 1e-6


def test_arf_interface():
    m = ARFModel(n_models=5, max_depth=5, lambda_value=5)
    for x, y in _stream():
        m.learn_one(x, y)
    proba = m.predict_proba_one({"f0": 0.9, "f1": 0.1})
    assert set(proba) == {0, 1}
    assert m.predict_one({"f0": 0.1, "f1": 0.1}) in (0, 1)


def test_ensemble_media():
    m1 = FTRLModel()
    m2 = ARFModel(n_models=3, max_depth=3, lambda_value=3)
    ens = EnsembleModel([m1, m2], vote="mean")
    for x, y in _stream():
        ens.learn_one(x, y)
    proba = ens.predict_proba_one({"f0": 0.8, "f1": 0.2})
    assert set(proba) == {0, 1}


def test_metricas_sinteticas():
    rng = np.random.default_rng(1)
    scores = np.concatenate([rng.normal(1.0, 0.5, 100), rng.normal(-1.0, 0.5, 100)])
    labels = np.concatenate([np.ones(100), np.zeros(100)])
    auc = roc_auc(scores, labels)
    assert 0.9 <= auc <= 1.0
    e = eer(scores, labels)
    assert 0.0 <= e <= 0.2
    tpr = tpr_at_fpr(scores, labels, 0.03)
    assert tpr >= 0.5
    r = resumo(scores, labels)
    assert r["n_pos"] == 100 and r["n_neg"] == 100


def test_metricas_perfeitas():
    scores = np.array([1.0, 1.0, 0.0, 0.0])
    labels = np.array([1, 1, 0, 0])
    assert roc_auc(scores, labels) == pytest.approx(1.0)
    assert eer(scores, labels) == pytest.approx(0.0)


def test_metricas_classes_ausentes():
    assert np.isnan(roc_auc([0.5, 0.4], [1, 1]))
    assert np.isnan(eer([0.5, 0.4], [1, 1]))


def test_operating_point_qp4():
    # positivos com score alto, negativos com score baixo: operando com FPR <= 3%
    scores = np.concatenate([np.full(90, 0.8), np.full(90, 0.2)])
    labels = np.concatenate([np.ones(90, dtype=np.int64), np.zeros(90, dtype=np.int64)])
    op = operating_point(scores, labels, 0.03)
    assert op["tpr"] == pytest.approx(1.0)
    assert op["fpr"] <= 0.03
    assert 0.0 < op["precisao"] <= 1.0
    assert op["recall"] == pytest.approx(op["tpr"])
    assert 0.0 < op["f1"] <= 1.0


def test_operating_point_classe_unica():
    op = operating_point([0.5, 0.4], [1, 1])
    assert all(np.isnan(op[k]) for k in ("tpr", "fpr", "precisao", "recall", "f1"))


def test_operating_point_sem_limiar():
    # nenhum limiar atinge FPR <= 3% (todas as negativas com score alto)
    scores = [0.9, 0.9, 0.9]
    labels = [1, 0, 0]
    op = operating_point(scores, labels, 0.03)
    assert op["tpr"] == 0.0 or op["f1"] == 0.0


def test_dqn_aprende():
    agent = demo_dqn(episodes=200, seed=7)
    assert agent.epsilon < 0.5  # decaiu com o treino
    step_fn = synthetic_risk_mdp()
    rng = np.random.default_rng(3)
    acoes = set()
    for _ in range(60):
        s = rng.uniform(0, 1, 10)
        a = agent.act(s, explore=False)
        acoes.add(a)
        s2, _, done = step_fn(s, a)
        assert done
    assert acoes <= {0, 1, 2}


def test_dqn_replay_e_learn():
    agent = DQNAgent(n_features=4, n_actions=2, batch_size=8, seed=1)
    rng = np.random.default_rng(5)
    for _ in range(200):
        s = rng.uniform(0, 1, 4)
        a = agent.act(s)
        s2 = rng.uniform(0, 1, 4)
        agent.remember(s, a, 1.0, s2, True)
        agent.learn()
    assert len(agent.buffer) == 200

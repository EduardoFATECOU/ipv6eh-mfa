"""Interface comum de modelos online e wrappers FTRL/ARF/DQN.

Os cenarios C1-C4 usam aprendizado incremental (stream), entao a interface
baseada em instancias (learn_one / predict_proba_one) espelha o fluxo de
dados continuo da autenticacao continua.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterable, Optional, Sequence

import numpy as np


class OnlineModel(ABC):
    """Contrato minimo dos modelos online (FTRL e ARF)."""

    @abstractmethod
    def learn_one(self, x: Dict, y: int) -> None:
        """Atualiza o modelo com uma unica instancia."""

    @abstractmethod
    def predict_proba_one(self, x: Dict) -> Dict[int, float]:
        """Retorna {classe: probabilidade} para uma instancia."""

    @abstractmethod
    def predict_one(self, x: Dict) -> int:
        """Retorna a classe com maior probabilidade."""


class FTRLModel(OnlineModel):
    """Regressao logistica com otimizador FTRL-Proximal (River).

    Referencia: McMahan et al. (2013), 'Ad Click Prediction: a View from
    the Trenches' (FTRL-Proximal).
    """

    def __init__(
        self,
        alpha: float = 0.05,
        beta: float = 1.0,
        l1: float = 0.0,
        l2: float = 1.0,
    ):
        from river.linear_model import LogisticRegression
        from river.optim import FTRLProximal

        self._model = LogisticRegression(
            optimizer=FTRLProximal(alpha=alpha, beta=beta, l1=l1, l2=l2),
        )

    def learn_one(self, x: Dict, y: int) -> None:
        self._model.learn_one(x, y)

    def predict_proba_one(self, x: Dict) -> Dict[int, float]:
        return self._model.predict_proba_one(x)

    def predict_one(self, x: Dict) -> int:
        return self._model.predict_one(x)


class ARFModel(OnlineModel):
    """Adaptive Random Forest com ADWIN (River), CVR + FPR monitorados.

    Referencia: Gomes et al. (2017), 'Adaptive Random Forests for
    Evolving Data Stream Classification' (ADWIN no background).
    """

    def __init__(
        self,
        n_models: int = 10,
        max_depth: int = 10,
        max_size: int = 500,
        lambda_value: int = 10,
        drift_detector: str = "adwin",
        seed: int = 42,
    ):
        from river.ensemble import ADWINBaggingClassifier
        from river.tree import HoeffdingAdaptiveTreeClassifier

        if drift_detector == "adwin":
            from river.drift import ADWIN

            detector = ADWIN()
        elif drift_detector == "ddm":
            from river.drift import DDM

            detector = DDM()
        else:
            raise ValueError(f"drift_detector desconhecido: {drift_detector}")

        base = HoeffdingAdaptiveTreeClassifier(
            max_depth=max_depth,
            max_size=max_size,
            leaf_prediction="nba",
            drift_detector=detector,
            seed=seed,
        )
        self._model = ADWINBaggingClassifier(
            model=base,
            n_models=n_models,
            seed=seed,
        )
        self._lambda = lambda_value

    def learn_one(self, x: Dict, y: int) -> None:
        self._model.learn_one(x, y)

    def predict_proba_one(self, x: Dict) -> Dict[int, float]:
        return self._model.predict_proba_one(x)

    def predict_one(self, x: Dict) -> int:
        return self._model.predict_one(x)


def featurize(vec: Sequence[float], names: Optional[Sequence[str]] = None) -> Dict:
    """Converte um vetor numerico em dicionario nome->valor (formato River)."""
    names = names if names is not None else [f"f{i}" for i in range(len(vec))]
    return {name: float(value) for name, value in zip(names, vec)}


def mean_proba(class_proba: Iterable[Dict[int, float]]) -> Dict[int, float]:
    """Media das probabilidades de um stream de predicoes."""
    counts = {}
    sums = {}
    for proba in class_proba:
        for cls, p in proba.items():
            sums[cls] = sums.get(cls, 0.0) + p
            counts[cls] = counts.get(cls, 0) + 1
    n = sum(counts.values())
    return {cls: s / n for cls, s in sums.items()}


class EnsembleModel(OnlineModel):
    """Comite de modelos online; decisao por media de probabilidades."""

    def __init__(self, models: Sequence[OnlineModel], vote: str = "mean"):
        if vote not in ("mean", "max"):
            raise ValueError(f"voto desconhecido: {vote}")
        self._models = list(models)
        self.vote = vote

    def learn_one(self, x: Dict, y: int) -> None:
        for model in self._models:
            model.learn_one(x, y)

    def predict_proba_one(self, x: Dict) -> Dict[int, float]:
        probas = [m.predict_proba_one(x) for m in self._models]
        classes = set()
        for p in probas:
            classes.update(p.keys())
        if self.vote == "max":
            out = {}
            for cls in classes:
                out[cls] = max((p.get(cls, 0.0) for p in probas), default=0.0)
            total = sum(out.values()) or 1.0
            return {cls: v / total for cls, v in out.items()}
        return mean_proba(probas)

    def predict_one(self, x: Dict) -> int:
        proba = self.predict_proba_one(x)
        return max(proba, key=proba.get)

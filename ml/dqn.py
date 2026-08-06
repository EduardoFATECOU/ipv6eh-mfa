"""DQN (Deep Q-Network) implementado em NumPy puro.

Nao depende de TensorFlow/Keras, permitindo rodar o pipeline em qualquer
ambiente (inclusive Windows sem GPU). A arquitetura segue o Cap. 7:
estado com 10 dimensoes, duas camadas ocultas (64, 32) e 25 acoes.

A DQN e usada no Agente Decisor (AD): a partir do estado agregado
(confiancas dos fatores + risco de contexto) o agente escolhe a acao de
autenticacao e recebe a recompensa do ambiente simulado (cenarios C1-C4).
Aqui o treinamento e validado em um MDP sintetico de referencia, garantindo
que o pipeline RL esteja correto antes da integracao no ambiente real.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class ReplayBuffer:
    """Buffer de experiencia (amostra uniforme, FIFO)."""

    capacity: int = 10000
    _buffer: Deque = field(default_factory=deque)

    def push(self, state, action, reward, next_state, done) -> None:
        self._buffer.append((state, action, reward, next_state, done))
        if len(self._buffer) > self.capacity:
            self._buffer.popleft()

    def sample(self, batch_size: int) -> Optional[Tuple]:
        if len(self._buffer) < batch_size:
            return None
        indices = np.random.choice(len(self._buffer), batch_size, replace=False)
        return tuple(zip(*(self._buffer[i] for i in indices)))

    def __len__(self) -> int:
        return len(self._buffer)


class DQN:
    """Redes Q (online + target) com camadas (64, 32) e ReLU.

    Propagacao direta:

        h1 = relu(W1 @ x + b1)    64
        h2 = relu(W2 @ h1 + b2)   32
        q  = W3 @ h2 + b3         n_actions
    """

    def __init__(
        self,
        n_features: int,
        n_actions: int,
        *,
        hidden: Sequence[int] = (64, 32),
        seed: int = 42,
        tau: float = 0.05,
    ):
        self.n_features = n_features
        self.n_actions = n_actions
        self.tau = tau
        rng = np.random.default_rng(seed)
        layers = [n_features, *hidden, n_actions]
        self.weights: List[np.ndarray] = []
        self.biases: List[np.ndarray] = []
        for i in range(len(layers) - 1):
            fan_in = layers[i]
            gain = np.sqrt(2.0 / fan_in) if i < len(layers) - 2 else 1.0
            self.weights.append(rng.normal(0.0, gain, (layers[i + 1], fan_in)))
            self.biases.append(np.zeros(layers[i + 1]))
        # Target network (copia soft periodicamente)
        self.target_weights = [w.copy() for w in self.weights]
        self.target_biases = [b.copy() for b in self.biases]

    def forward(self, x: np.ndarray, weights, biases) -> np.ndarray:
        h = np.asarray(x, dtype=np.float64)
        single = h.ndim == 1
        if single:
            h = h.reshape(1, -1)
        n = len(weights)
        for i in range(n - 1):
            h = np.maximum(0.0, h @ weights[i].T + biases[i])
        out = h @ weights[-1].T + biases[-1]
        return out[0] if single else out

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x, self.weights, self.biases)

    def target_predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x, self.target_weights, self.target_biases)

    def soft_update(self) -> None:
        for w, tw in zip(self.weights, self.target_weights):
            tw += self.tau * (w - tw)
        for b, tb in zip(self.biases, self.target_biases):
            tb += self.tau * (b - tb)


class DQNAgent:
    """Agente RL epsilon-greedy com replay, target network e gradiente
    em NumPy (MSE sobre o TD target r + gamma * max_a Q_target(s', a))."""

    def __init__(
        self,
        n_features: int,
        n_actions: int,
        *,
        gamma: float = 0.95,
        lr: float = 1e-3,
        epsilon: float = 1.0,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
        batch_size: int = 64,
        buffer_capacity: int = 10000,
        seed: int = 42,
    ):
        self.net = DQN(n_features, n_actions, seed=seed)
        self.gamma = gamma
        self.lr = lr
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.buffer = ReplayBuffer(capacity=buffer_capacity)
        self.rng = np.random.default_rng(seed)

    def act(self, state: Sequence[float], *, explore: bool = True) -> int:
        if explore and self.rng.random() < self.epsilon:
            return int(self.rng.integers(0, self.net.n_actions))
        q = self.net.predict(np.asarray(state, dtype=np.float64))
        return int(np.argmax(q))

    def remember(self, state, action, reward, next_state, done) -> None:
        self.buffer.push(
            np.asarray(state, dtype=np.float64),
            int(action),
            float(reward),
            np.asarray(next_state, dtype=np.float64),
            bool(done),
        )

    def learn(self, batch_size: Optional[int] = None, steps: int = 1) -> float:
        bs = batch_size or self.batch_size
        batch = self.buffer.sample(bs)
        if batch is None:
            return 0.0
        loss = 0.0
        for _ in range(steps):
            batch = self.buffer.sample(bs)
            if batch is None:
                continue
            states, actions, rewards, next_states, dones = batch
            states = np.stack(states)
            next_states = np.stack(next_states)
            rewards = np.asarray(rewards, dtype=np.float64)
            actions = np.asarray(actions, dtype=np.int64)
            dones = np.asarray(dones, dtype=np.float64)

            q_next = self.net.target_predict(next_states).max(axis=1)
            targets = rewards + self.gamma * q_next * (1.0 - dones)
            q_all = self.net.predict(states)

            # Gradiente de MSE em relacao a Q da acao escolhida
            q_sa = q_all[np.arange(len(states)), actions]
            grad = 2.0 * (q_sa - targets) / max(bs, 1)
            dW = [np.zeros_like(w) for w in self.net.weights]
            dB = [np.zeros_like(b) for b in self.net.biases]
            for i, (s, a, g) in enumerate(zip(states, actions, grad)):
                gq = np.zeros(self.net.n_actions)
                gq[a] = g
                h = np.asarray(s, dtype=np.float64)
                activations = [h]
                n = len(self.net.weights)
                for j in range(n - 1):
                    h = np.maximum(0.0, self.net.weights[j] @ h + self.net.biases[j])
                    activations.append(h)
                delta = gq
                for j in range(n - 1, -1, -1):
                    dB[j] += delta
                    dW[j] += np.outer(delta, activations[j])
                    if j > 0:
                        pre = self.net.weights[j - 1] @ activations[j - 1] + self.net.biases[j - 1]
                        delta = (self.net.weights[j].T @ delta) * (pre > 0)
            for j in range(len(self.net.weights)):
                self.net.weights[j] -= self.lr * dW[j] / bs
                self.net.biases[j] -= self.lr * dB[j] / bs
            loss += float(np.mean((q_all[np.arange(len(states)), actions] - targets) ** 2))

        self.net.soft_update()
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
        return loss / max(steps, 1)


def synthetic_risk_mdp():
    """MDP sintetico de referencia para validar a DQN.

    Estado: 10 dimensoes (5 confiancas de fator + 3 de contexto de risco +
    drift + passo). Acao 0 = aceitar; 1 = solicitar TOTP; 2 = bloquear.
    A politica otima aceita se a confianca media for alta, solicita fator
    adicional em risco medio e bloqueia em risco alto.
    """

    def step(state, action):
        conf_mean = float(np.mean(state[:5]))
        risk = float(np.mean(state[5:8]))
        if action == 2 or risk > 0.8:
            return np.zeros(10), -5.0, True
        if action == 0:
            return state, 1.0 if conf_mean >= 0.5 else -1.0, True
        return state, -0.1 + (0.5 if conf_mean >= 0.5 else 0.0), True

    return step


def demo_dqn(episodes: int = 300, seed: int = 42) -> DQNAgent:
    """Treina a DQN no MDP sintetico e retorna o agente.

    Retorno: agente com epsilon ja decaido; usado em teste/smoke.
    """
    step_fn = synthetic_risk_mdp()
    agent = DQNAgent(n_features=10, n_actions=3, seed=seed, epsilon_decay=0.99)
    rng = np.random.default_rng(seed)
    for _ in range(episodes):
        state = rng.uniform(0.0, 1.0, 10)
        done = False
        while not done:
            action = agent.act(state)
            next_state, reward, done = step_fn(state, action)
            agent.remember(state, action, reward, next_state, done)
            state = next_state
        agent.learn()
    return agent

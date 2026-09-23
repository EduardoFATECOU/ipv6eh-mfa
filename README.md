# Implementacao de referencia - Cap. 7 da tese

Sistema multiagente (SPADE/XMPP) para autenticacao continua e adaptativa
baseada em cabecalhos IPv6 e IPSec (RFC 3692 / RFC 4727 / RFC 9099).

## Estrutura

```
am_agent/   Agente Monitor: coleta da opcao MFA + features + ReplayDefender (C3)
ad_agent/   Agente Decisor: politica plugavel (regras/FTRL/ARF/DQN) + tratamento de replay
aa_agent/   Agente Auditoria: registro HMAC + metricas online
protocol/   Opcao 0x1E em IPv6 Destination Options (20 bytes), Scapy + replay.py (nonce/timestamp)
ml/         FTRL-Proximal, ARF (ADWIN) e DQN (NumPy) com interface comum
ipsec/      Templates StrongSwan (ipsec.conf, secrets, pki.sh)
attacks/    Cenarios C1-C4 (30 repeticoes) + gerador do dataset IPv6-EH
eval/       Metricas (AUC/EER/TPR@FPR<=3%) + baselines + simulador C1-C4 + stats
tests/      pytest (protocol, ml, metricas, agentes, dataset)
data/       Datasets publicos (CMU Keystroke, Balabit) e gerado (ipv6eh)
```

## Requisitos e execucao

```bash
pip install -r requirements.txt
pytest tests -q
python -m eval.run_all        # baselines CMU + Balabit -> eval/results/
python -m eval.baseline_keystroke   # so CMU
python -m eval.baseline_balabit     # so Balabit
```

Para deploy automatizado nas 4 VMs (AWS ou VirtualBox):
```bash
./deploy_vms.sh aws     # ou ./deploy_vms.sh local
```

## Dataset IPv6-EH (Anexo B)

Gera ~500.000 eventos de autenticacao continua com 10 features contextuais
(derivadas das 10 dimensoes do estado da DQN) e o rotulo da classe, em
`data/ipv6eh/` (CSV + Parquet + metadata.json + README.md):

```bash
python -m attacks.generate_dataset
```

- Rotulos: 0=legitimo; 1=C1 Roubo de Credenciais; 2=C2 MITM; 3=C3 Replay;
  4=C4 Spoofing de Agente (Cap. 5 §5.5.1).
- Deterministico (semente em metadata.json); validacao embutida
  (`checar_separabilidade`): AUC por cenario com FTRL + normalizacao z-score
  (C1 ~1.00, C2 ~0.999, C4 ~0.996, C3 ~0.946 — replay e o mais dificil).

## Protocolo MFA (protocol/)

O Option Type 0x1E (bits 7-6 = 01, bit 5 = 1) carrega 20 bytes de Option
Data em um IPv6 Destination Options Header:

| offset | tamanho | campo |
|---|---|---|
| 0 | 1 | factor_type (1-5) |
| 1 | 1 | version (0x01) |
| 2 | 2 | confidence (0-10000 = 0,00%-100,00%) |
| 4 | 4 | timestamp Unix |
| 8 | 8 | agent_id (SHA-256 truncado) |
| 16 | 4 | nonce (anti-replay) |

Exemplo de uso:

```python
from protocol.mfa_option import build_option_data, make_destopts_packet, extract_option_from_bytes

data = build_option_data(2, 0.9, agent_key="vm-cliente-01")
pkt = make_destopts_packet(data, src="2001:db8::10", dst="2001:db8::20")
cred = extract_option_from_bytes(bytes(pkt))
```

## Baselines academicos (dados publicos)

Resultados em `eval/results/RESUMO.md`. Protocolos:

- **CMU Keystroke** (Killourhy & Maxion, 2009): 51 usuarios x 400 reps;
  por usuario, treino com 200 genuinas + 200 impostoras e teste com as
  200 restantes de cada classe.
- **Balabit** (Fulop et al., 2016): 10 usuarios; features agregadas por
  sessao (velocidade/aceleracao/posicao), padronizadas via z-score
  (estatisticas apenas do treino, clipping em [-5,5]); treino com as
  sessoes genuinas do usuario + as dos demais e teste nas sessoes
  rotuladas em public_labels.csv (is_illegal).

Hyperparametros fixos (mesmos nos dois datasets): FTRL alpha=0.05,
beta=1.0, l1=0.0, l2=1.0; ARF 10 modelos, profundidade 10, ADWIN.

## DQN

Implementada em NumPy puro (sem TensorFlow/Keras): camadas (64, 32),
replay buffer, target network (soft update) e epsilon-greedy. Estado com
10 dimensoes (5 confiancas de fator + contexto de risco) e 25 acoes no
Ambiente real; aqui e validada num MDP sintetico de referencia
(ml/dqn.synthetic_risk_mdp).

## Simulacao local da campanha C1-C4 (eval/simulador.py)

Reexecuta em um unico host a avaliacao do Cap. 8 sobre o dataset proprio,
implementando o protocolo do Anexo B.4 (prever -> medir -> aprender,
normalizacao z-score so no aquecimento, drift por janelas temporais):

```bash
# validacao rapida
python -m eval.simulador --reps 3 --eventos 12000 --warm 1000
# campanha da tese (30 repeticoes; ~1h40m)
python -m eval.simulador --reps 30 --eventos 20000 --warm 2000
```

Saidas em `eval/results/` (`simulacao_det.csv`, `simulacao_dqn.csv`,
`simulacao_drift.csv`, `SIMULACAO.md`):

- **Detectores** (FTRL, ARF, Ensemble): AUC/EER/TPR@FPR<=3% por cenario,
  latencia P50/P95/P99 de inferencia e deteccoes de drift (ADWIN).
- **DQN** (Agente Decisor): politica 10 dims / 3 acoes
  (permitir/desafiar/bloquear) com recompensas assimetricas (fail-secure),
  reportada em modo greedy; TPR/FPR operacionais e taxas de bloqueio/escalada.
- **Estatistica**: teste de Friedman (com correcao de Iman-Davenport) e
  post-hoc de Nemenyi sobre as repeticoes (`eval/stats.py`, NumPy puro).
- **Protocolo 0x1E**: latencia de build/parse/pacote Scapy.

Resultado da campanha (5 reps x 15k eventos, seed 42): FTRL e Ensemble
atingem TPR>=95% com FPR<=3% em C1, C2 e C4; C3 (Replay) e o mais dificil
(~0.73-0.76), coerente com a separabilidade do Anexo B. O Ensemble (media
FTRL+ARF) domina os rankings nos cenarios em que Friedman rejeita H0.

## Notas

- `l1=0.0` no FTRL: o default do McMahan (l1=1.0) colapsa em dados
  escassos (5-7 sessoes de treino no Balabit).
- O agente SPADE e importado apenas quando `pip install spade` estiver
  disponivel (ambiente de experimentacao); os testes nao dependem dele.
- O pdf/docs da tese sao gerados em
  `C:\Users\Eduardo\Downloads\Doutorado\` (ver `roteiro_tese.md`).

## Licenca e dados

Codigo sob licenca MIT (projeto LARS/UNESP). Os datasets possuem licencas
de uso academico proprias (ver `roteiro_tese.md`, Secao 6).

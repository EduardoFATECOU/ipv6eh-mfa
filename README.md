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
ipsec/      PKI (pki.sh) + template StrongSwan (modo transporte) + gerador por VM
attacks/    Cenarios C1-C4 (30 repeticoes) + gerador do dataset IPv6-EH
eval/       Metricas (AUC/EER/TPR@FPR<=3%) + baselines + simulador C1-C4 + runner + stats
tests/      pytest (protocol, ml, metricas, agentes, dataset)
agent_entry.py  Entrypoint compartilhado (`python -m am_agent|ad_agent|aa_agent`)
verificar_ambiente.sh  Auditoria do ambiente das VMs (Fase 0.7, exit 0 = pronto)
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

## Execucao dos agentes (4 VMs)

Os agentes rodam como servico systemd (`systemd/am.service`, `ad.service`,
`aa.service`) e usam SPADE sobre XMPP. No servidor de experimentos:

```bash
python3 -m pip install -r requirements-vm.txt   # inclui spade e psutil
python3 -m am_agent --check    # valida a configuracao sem conectar ao XMPP
python3 -m am_agent            # inicia o Agente Monitor
python3 -m ad_agent            # inicia o Agente Decisor
python3 -m aa_agent            # inicia o Agente Auditoria
```

Configuracao por variaveis de ambiente (ver `/etc/mfa/agent.env`):
`MFA_JID`, `MFA_PASSWORD`, `MFA_LOG_LEVEL`, `MFA_AD_JID`, `MFA_AA_JID`,
`MFA_AUDIT_DIR`, `MFA_AUDIT_KEY`.

Deploy automatizado nas 4 VMs:

```bash
./deploy_vms.sh local                 # VirtualBox / SSH ja configurado
./deploy_vms.sh aws --key chave.pem   # AWS Academy (EC2)
./deploy_vms.sh local --dry-run       # mostra o plano sem executar
```

O script sincroniza o codigo, instala dependencias (`apt` + `requirements-vm.txt` em
venv), grava `/etc/mfa/agent.env` e habilita o servico `mfa-agent` em cada VM.
Opcoes: `--user`, `--key`, `--hosts`, `--domain`, `--ipv6-iface`, `--skip-deps`,
`--skip-ipsec`.

## PKI e IPSec (modo transporte)

A PKI e gerada uma vez na maquina de controle (com `strongswan-pki`) e o
deploy a distribui:

```bash
cd implementacao/ipsec
bash pki.sh --dry-run    # confere o plano
bash pki.sh              # ipsec/pki/: CA + 4 certificados ECDSA P-256
```

`pki.sh` cria `ca-key.pem`, `ca-cert.pem` e `<vm>-{key,pub,cert}.pem` para
cliente/servidor/gateway/auditor (SAN = FQDN + IPv6). A pasta `ipsec/pki/` e
ignorada pelo git - nunca versione as chaves. A chave da CA vai apenas para a
VM4 (AA), que mantem a autoridade certificadora (Cap. 7).

O `deploy_vms.sh` copia a CA, os 4 certificados e a chave da VM para
`/etc/ipsec.d/`, renderiza `/etc/ipsec.conf` com `gerar_conf.sh` e grava
`/etc/ipsec.secrets`. A configuracao segue Cap. 5/7 e Anexo C: **ESP em modo
transporte**, AES-256-GCM, lifetime 8 h / 100 MB e autenticacao mutua por
X.509 (uma conexao por par, host-to-host).

| VM | Nome | IPv6 | Papel |
|---|---|---|---|
| VM1 | cliente | `2001:db8:1::10` | AM |
| VM2 | servidor | `2001:db8:2::11` | AM |
| VM3 | gateway | `2001:db8:2::12` | AD |
| VM4 | auditor | `2001:db8:2::13` | AA |

Para configurar os enderecos durante o deploy: `--ipv6-iface enp0s8` (o nome
da interface varia no VirtualBox/EC2). Para pular o IPSec: `--skip-ipsec`.

## Verificacao do ambiente (Fase 0.7)

Rode em cada VM (de preferencia com `sudo`, para ler `/etc/mfa` e o IPSec):

```bash
bash verificar_ambiente.sh
bash verificar_ambiente.sh --skip-xmpp   # Prosody ainda nao configurado (Fase 0.3)
```

O script audita sete blocos: **sistema** (distro, kernel, Python >= 3.10, RAM,
disco), **dependencias** (`spade`, `scapy`, `sklearn`, `river`, `psutil`,
`tensorflow`), **agente** (`/etc/mfa/agent.env`, `mfa-agent` ativo e `--check`
do modulo), **IPv6** (endereco global e `ping6` nos peers), **NTP**
(`chronyc tracking` com desvio <= 30 s, janela do ReplayDefender), **IPSec**
(SAs `ESTABLISHED`, CHILD_SAs `INSTALLED`, permissoes de `ipsec.secrets` e das
chaves) e **XMPP** (TCP 5222 no servidor).

Cada linha e `[ OK ]`, `[AVISO]` ou `[FALHA]`. O codigo de saida e **0 somente
se nao houver falhas**; avisos nao reprovam o ambiente. Principais opcoes:
`--ipv6-iface`, `--ipv6-peers "ip1 ip2"`, `--xmpp-host`, `--esperadas 3`,
`--max-offset 30` e `--skip-sistema|--skip-deps|--skip-agente|--skip-ipv6|--skip-ntp|--skip-ipsec|--skip-xmpp`.

O `deploy_vms.sh` executa o verificador ao final de cada VM (informativo, nao
interrompe o deploy); use `--skip-verificador` para omitir.

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
`simulacao_drift.csv`, `SIMULACAO.md`). Apenas os artefatos canonicos da tese
sao versionados; logs de execucao (`*.log`) e backups de smoke test
(`smoke_*/`) ficam fora do repositorio:

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

## Runner dos experimentos C1-C4 (eval/experimentos_vms.py)

Executa o smoke test ou a campanha e grava um CSV com TPR, FPR, AUC, EER,
precisao/recall/F1, latencia (P50/P95/P99), CPU/RSS, bloqueios e escaladas
(uma linha por repeticao x modelo):

```bash
# smoke test (1 repeticao)
python -m eval.experimentos_vms --cenario C1 --reps 1 --seed 42 \
       --saida eval/results/smoke_vm

# campanha simulada (4 cenarios x 30 repeticoes)
python -m eval.experimentos_vms --cenario ALL --reps 30 --seed 42 \
       --saida eval/results/vm_2026-XX-XX/simulado
```

Fontes:

| `--fonte` | Entrada | Uso |
|---|---|---|
| `simulado` (padrao) | dataset IPv6-EH (`data/ipv6eh/`) | referencia e smoke test |
| `coleta` / `vm` | `--audit-log eventos.jsonl --rotulos rotulos.csv` | logs reais do AA |

Na coleta, o score de risco e `1 - confianca` do AD (fallback: acao) e os
campos opcionais `latencia_ms`, `cpu_pct`, `rss_mb` e `rep` do JSONL sao
agregados por repeticao. O CSV de rotulos aceita `0..4`, `legitimo` e
`C1..C4`.

## Notas

- `l1=0.0` no FTRL: o default do McMahan (l1=1.0) colapsa em dados
  escassos (5-7 sessoes de treino no Balabit).
- O agente SPADE e importado apenas quando `pip install spade` estiver
  disponivel (ambiente de experimentacao); os testes nao dependem dele.
- O pdf/docs da tese sao gerados em
  `D:\Armazenamento\Documentos - Eduardo\Doutorado\` (ver `roteiro_tese.md`).

## Licenca e dados

Codigo sob licenca MIT (projeto LARS/UNESP). Os datasets possuem licencas
de uso academico proprias (ver `roteiro_tese.md`, Secao 6).

# Simulacao local - campanha C1-C4 (Cap. 8)


- Fluxo por repeticao: 20000 eventos; repeticoes: 30; modelos: FTRL, ARF, ENSEMBLE.
- Protocolo de avaliacao: prever -> medir -> aprender (Anexo B.4); normalizacao z-score so no aquecimento (sem vazamento).

## Detectores (Tabelas 8.x)

**C1**

| Modelo | AUC | EER | TPR@FPR<=3% | Precisao | F1 | P95 (us) | Drift |
|---|---:|---:|---:|---:|---:|---:|---:|
| FTRL | 0.9999 ± 0.0002 | 0.0013 ± 0.0022 | 0.9996 ± 0.0012 | 0.7793 ± 0.0214 | 0.8757 ± 0.0135 | 6.2 | 21.1 |
| ARF | 1.0000 ± 0.0001 | 0.0015 ± 0.0009 | 0.9999 ± 0.0004 | 0.7794 ± 0.0214 | 0.8758 ± 0.0135 | 506.5 | 21.4 |
| ENSEMBLE | 0.9999 ± 0.0002 | 0.0005 ± 0.0010 | 0.9998 ± 0.0005 | 0.7794 ± 0.0214 | 0.8758 ± 0.0135 | 522.2 | 116.0 |


**C2**

| Modelo | AUC | EER | TPR@FPR<=3% | Precisao | F1 | P95 (us) | Drift |
|---|---:|---:|---:|---:|---:|---:|---:|
| FTRL | 0.9970 ± 0.0017 | 0.0227 ± 0.0047 | 0.9810 ± 0.0071 | 0.7767 ± 0.0282 | 0.8667 ± 0.0191 | 6.2 | 21.1 |
| ARF | 0.9956 ± 0.0029 | 0.0222 ± 0.0060 | 0.9824 ± 0.0091 | 0.7770 ± 0.0277 | 0.8674 ± 0.0181 | 506.5 | 21.4 |
| ENSEMBLE | 0.9977 ± 0.0020 | 0.0138 ± 0.0039 | 0.9915 ± 0.0047 | 0.7785 ± 0.0276 | 0.8719 ± 0.0181 | 522.2 | 116.0 |


**C3**

| Modelo | AUC | EER | TPR@FPR<=3% | Precisao | F1 | P95 (us) | Drift |
|---|---:|---:|---:|---:|---:|---:|---:|
| FTRL | 0.9448 ± 0.0051 | 0.1312 ± 0.0080 | 0.7230 ± 0.0187 | 0.7280 ± 0.0335 | 0.7251 ± 0.0207 | 6.2 | 21.1 |
| ARF | 0.9096 ± 0.0139 | 0.1603 ± 0.0136 | 0.6891 ± 0.0295 | 0.7183 ± 0.0339 | 0.7028 ± 0.0244 | 506.5 | 21.4 |
| ENSEMBLE | 0.9442 ± 0.0078 | 0.1292 ± 0.0097 | 0.7567 ± 0.0180 | 0.7369 ± 0.0322 | 0.7462 ± 0.0195 | 522.2 | 116.0 |


**C4**

| Modelo | AUC | EER | TPR@FPR<=3% | Precisao | F1 | P95 (us) | Drift |
|---|---:|---:|---:|---:|---:|---:|---:|
| FTRL | 0.9925 ± 0.0019 | 0.0346 ± 0.0047 | 0.9630 ± 0.0074 | 0.7780 ± 0.0267 | 0.8604 ± 0.0176 | 6.2 | 21.1 |
| ARF | 0.9825 ± 0.0043 | 0.0577 ± 0.0089 | 0.9142 ± 0.0196 | 0.7688 ± 0.0286 | 0.8350 ± 0.0219 | 506.5 | 21.4 |
| ENSEMBLE | 0.9939 ± 0.0019 | 0.0312 ± 0.0046 | 0.9679 ± 0.0071 | 0.7789 ± 0.0266 | 0.8629 ± 0.0176 | 522.2 | 116.0 |


**GLOBAL**

| Modelo | AUC | EER | TPR@FPR<=3% | Precisao | F1 | P95 (us) | Drift |
|---|---:|---:|---:|---:|---:|---:|---:|
| FTRL | 0.9832 ± 0.0018 | 0.0611 ± 0.0039 | 0.9149 ± 0.0081 | 0.9301 ± 0.0062 | 0.9224 ± 0.0048 | 6.2 | 21.1 |
| ARF | 0.9713 ± 0.0042 | 0.0739 ± 0.0071 | 0.8943 ± 0.0143 | 0.9286 ± 0.0063 | 0.9111 ± 0.0079 | 506.5 | 21.4 |
| ENSEMBLE | 0.9836 ± 0.0023 | 0.0564 ± 0.0044 | 0.9274 ± 0.0075 | 0.9310 ± 0.0061 | 0.9292 ± 0.0043 | 522.2 | 116.0 |


## Politica do Agente Decisor (DQN)

Ponto de operacao calibrado (FPR<=3%) sobre o score Q(bloquear)-Q(permitir), mais a politica greedy reportada.

| Cenario | TPR cal. | FPR cal. | Precisao | F1 | Bloqueio | Escalada | P95 (us) |
|---|---:|---:|---:|---:|---:|---:|---:|
| C1 | 0.9789 | 0.0300 | 0.7756 | 0.8653 | 0.2799 | 0.0639 | 53.3 |
| C2 | 0.9350 | 0.0300 | 0.7681 | 0.8430 | 0.2799 | 0.0639 | 53.3 |
| C3 | 0.6218 | 0.0300 | 0.6969 | 0.6565 | 0.2799 | 0.0639 | 53.3 |
| C4 | 0.9332 | 0.0300 | 0.7726 | 0.8449 | 0.2799 | 0.0639 | 53.3 |
| GLOBAL | 0.8650 | 0.0300 | 0.9264 | 0.8945 | 0.2799 | 0.0639 | 53.3 |

**Politica greedy (operacional):**

| Cenario | TPR | FPR |
|---|---:|---:|
| C1 | 0.9928 | 0.0949 |
| C2 | 0.9683 | 0.0949 |
| C3 | 0.7274 | 0.0949 |
| C4 | 0.9648 | 0.0949 |
| GLOBAL | 0.9119 | 0.0949 |


## Comparacao estatistica (Friedman + Nemenyi)

**Friedman/Nemenyi - C1 (auc)**

- FTRL: rank medio 2.000
- ARF: rank medio 2.033
- ENSEMBLE: rank medio 1.967

- chi2(Friedman) = 0.067 (critico 0.05 = 5.991) | p = 0.9672 -> nao rejeita H0
- F (Iman-Davenport) = 0.032
- CD (Nemenyi, 0.05) = 0.605
- pares significativos: nenhum

**Friedman/Nemenyi - C2 (auc)**

- FTRL: rank medio 2.017
- ARF: rank medio 2.783
- ENSEMBLE: rank medio 1.200

- chi2(Friedman) = 37.617 (critico 0.05 = 5.991) | p = 0.0000 -> rejeita H0
- F (Iman-Davenport) = 48.736
- CD (Nemenyi, 0.05) = 0.605
- pares significativos: FTRL-ARF, FTRL-ENSEMBLE, ARF-ENSEMBLE

**Friedman/Nemenyi - C3 (auc)**

- FTRL: rank medio 1.400
- ARF: rank medio 3.000
- ENSEMBLE: rank medio 1.600

- chi2(Friedman) = 45.600 (critico 0.05 = 5.991) | p = 0.0000 -> rejeita H0
- F (Iman-Davenport) = 91.833
- CD (Nemenyi, 0.05) = 0.605
- pares significativos: FTRL-ARF, ARF-ENSEMBLE

**Friedman/Nemenyi - C4 (auc)**

- FTRL: rank medio 1.917
- ARF: rank medio 3.000
- ENSEMBLE: rank medio 1.083

- chi2(Friedman) = 55.417 (critico 0.05 = 5.991) | p = 0.0000 -> rejeita H0
- F (Iman-Davenport) = 350.636
- CD (Nemenyi, 0.05) = 0.605
- pares significativos: FTRL-ARF, FTRL-ENSEMBLE, ARF-ENSEMBLE

**Friedman/Nemenyi - GLOBAL (auc)**

- FTRL: rank medio 1.550
- ARF: rank medio 3.000
- ENSEMBLE: rank medio 1.450

- chi2(Friedman) = 45.150 (critico 0.05 = 5.991) | p = 0.0000 -> rejeita H0
- F (Iman-Davenport) = 88.172
- CD (Nemenyi, 0.05) = 0.605
- pares significativos: FTRL-ARF, ARF-ENSEMBLE


## Latencia do protocolo 0x1E


- build: P50 8.50 us, P95 9.40 us

- parse: P50 2.10 us, P95 2.40 us

- pacote (Scapy): P50 235.10 us, P95 246.50 us

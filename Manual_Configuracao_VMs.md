# Manual de Configuração - Ambiente de Experimentos (4 VMs)

Este manual descreve o processo de preparação das quatro máquinas virtuais (Ubuntu 24.04) para a execução do sistema de autenticação contínua.

## 1. Pré-requisitos
*   **SO:** Ubuntu 24.04 LTS instalado em todas as 4 máquinas.
*   **Rede:** Todas as VMs devem se comunicar na mesma sub-rede (ex: `192.168.1.0/24`).
*   **SSH:** Configurar chave SSH da sua máquina de controle para acesso sem senha a todas as VMs (usuário `ubuntu`).

## 1.1 Considerações para AWS EC2 (AWS Academy)
Se estiver utilizando AWS EC2 (`m7i-flex.large` — 2 vCPU, 8 GB RAM, 50 GB EBS — ou similar):
*   **Segurança (Security Groups):** Configure uma regra de entrada no Security Group permitindo todo o tráfego proveniente do próprio grupo de segurança (tráfego interno liberado entre as 4 VMs).
*   **IPs:** Utilize os **Endereços IPv4 Privados** das instâncias EC2 no script de deploy.
*   **Autenticação:** Tenha o arquivo `.pem` da sua chave de acesso AWS disponível na máquina de controle.

## 2. Preparação Manual (Executar em CADA uma das 4 VMs)
Antes de rodar o deploy, prepare o ambiente básico:

```bash
# 1. Atualizar e instalar dependências básicas
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv strongswan strongswan-pki libstrongswan-standard-plugins libcharon-extra-plugins rsync
```

## 3. Configuração da PKI (Segurança/IPSec)
A autenticação entre agentes depende de certificados X.509.
1.  Na sua máquina de controle, execute o script de PKI para gerar os certificados:
    ```bash
    cd implementacao/ipsec
    bash pki.sh
    ```
2.  O script `deploy_vms.sh` já copia os certificados gerados para as pastas corretas nas VMs.

## 4. Implantação Automatizada
Execute a partir da **máquina de controle**. O script aceita dois modos:

```bash
# VirtualBox (ou hosts com chave SSH já configurada)
./deploy_vms.sh local

# AWS Academy (EC2) — usa a chave .pem
./deploy_vms.sh aws --key ~/chave.pem

# Conferir o plano sem executar
./deploy_vms.sh local --dry-run
```

Opções: `--user`, `--key`, `--hosts "ip1 ip2 ip3 ip4"`, `--domain`, `--skip-deps`.

O deploy executa em cada VM: `rsync` do código, instalação via `apt`
(`python3-venv`, `strongswan`, `chrony`), venv + `requirements-vm.txt`,
`/etc/mfa/agent.env` e o serviço `mfa-agent`.

## 4.1. Variáveis de ambiente dos agentes

Cada VM lê `/etc/mfa/agent.env` (via `EnvironmentFile=` no systemd):

```bash
MFA_JID=monitor@lars.local
MFA_PASSWORD=senha_do_jid
MFA_AD_JID=decisor@lars.local     # usado pelo AM
MFA_AA_JID=auditor@lars.local     # usado pelo AD
MFA_AUDIT_DIR=/var/lib/mfa/logs   # apenas no AA
MFA_AUDIT_KEY=<32 bytes em hex>   # apenas no AA
```

## 5. Verificação e Monitoramento
Após o deploy, verifique se tudo está operando corretamente:

*   **Status do serviço (agente da VM):**
    ```bash
    sudo systemctl status mfa-agent
    ```
*   **Validação rápida da configuração (sem conectar ao XMPP):**
    ```bash
    cd ~/ipv6eh-mfa && python3 -m am_agent --check
    ```
*   **Logs do agente (para debug):**
    ```bash
    journalctl -u mfa-agent -f
    ```
*   **Status do túnel IPSec (StrongSwan):**
    ```bash
    sudo ipsec status
    ```

## 5.1. Runner dos experimentos (smoke test e campanha)

Na máquina de controle, rode o smoke test de uma repetição:

```bash
python -m eval.experimentos_vms --cenario C1 --reps 1 --seed 42 \
       --saida eval/results/smoke_vm
```

O CSV (`experimentos.csv`) traz TPR, FPR, AUC, EER, precisão/recall/F1,
latência P50/P95/P99, CPU/RSS, bloqueios e escaladas — uma linha por
repetição x modelo. Para analisar logs reais do AA, use a fonte `coleta`
(alias `vm`):

```bash
python -m eval.experimentos_vms --cenario C1 --fonte coleta \
       --audit-log /var/lib/mfa/logs/eventos.jsonl \
       --rotulos rotulos.csv --saida eval/results/vm/C1
```

A campanha oficial (30 repetições por cenário) está na Fase 7 de
`CHECKLIST_EXPERIMENTOS.md`.

## 6. Troubleshooting (Resolução de Problemas)

| Problema | Causa Provável | Ação de Diagnóstico/Correção |
| :--- | :--- | :--- |
| **Timeout no Deploy** | **AWS Security Group** | Verifique se o Security Group permite tráfego entre os IPs privados das instâncias. |
| **Agente não inicia** | Dependências/Erro de config | Verifique logs com `journalctl -u mfa-agent -e`. |
| **Túnel IPSec down** | Erro na PKI ou `ipsec.conf` | Verifique o status com `sudo ipsec statusall`. |
| **Agentes não se comunicam** | Rede/Firewall | Verifique se a porta XMPP (5222) está liberada no Security Group. |
| **Ataque C3 não detectado** | Time drift entre as VMs | Sincronize o tempo entre as VMs com `timedatectl`. O `ReplayDefender` depende de clocks sincronizados (NTP). |

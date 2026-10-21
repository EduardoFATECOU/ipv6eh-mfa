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

## 3. Configuração da PKI e do IPSec (modo transporte)

A autenticação entre agentes usa certificados X.509 (ECDSA P-256) e SAs
IPSec em **modo transporte** (Cap. 5/7 e Anexo C).

1.  Na máquina de controle (com `strongswan-pki` instalado), gere a PKI local:
    ```bash
    cd implementacao/ipsec
    bash pki.sh --dry-run   # confere o plano
    bash pki.sh             # ipsec/pki/: CA + 4 certificados
    ```
    Saída: `ca-cert.pem`, `ca-key.pem` e `<vm>-{key,pub,cert}.pem` para
    cliente/servidor/gateway/auditor. **Não versione** `ipsec/pki/`.
2.  O `deploy_vms.sh` distribui a PKI e o `ipsec.conf` (não é preciso copiar
    nada à mão): CA + 4 certificados em `/etc/ipsec.d/certs/`, chave privada
    em `/etc/ipsec.d/private/` (modo 600), `ipsec.secrets` e o
    `/etc/ipsec.conf` gerado por `gerar_conf.sh`. A chave da CA é instalada
    apenas na VM4 (AA), que mantém a autoridade certificadora.
3.  Endereços IPv6 do laboratório:

    | VM | Nome | IPv6 |
    |---|---|---|
    | VM1 | cliente | `2001:db8:1::10/64` |
    | VM2 | servidor | `2001:db8:2::11/64` |
    | VM3 | gateway | `2001:db8:2::12/64` |
    | VM4 | auditor | `2001:db8:2::13/64` |

    Para o deploy configurá-los: `--ipv6-iface <interface>`.
    Para pular o IPSec: `--skip-ipsec`.

> **Modo transporte:** preserva os cabeçalhos de extensão IPv6 que carregam a
> opção MFA (0x1E); o desafio MFA é feito pelo AD/AM, não pelo IKEv2.

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

Opções: `--user`, `--key`, `--hosts "ip1 ip2 ip3 ip4"`, `--domain`,
`--ipv6-iface`, `--skip-deps`, `--skip-ipsec`.

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
Após o deploy, verifique se tudo está operando corretamente.

A forma mais rápida é o **verificador automático** (Fase 0.7), que audita sete
blocos (sistema, dependências, agente, IPv6, NTP, IPSec e XMPP):

```bash
cd ~/ipv6eh-mfa
sudo bash verificar_ambiente.sh               # ambiente completo
sudo bash verificar_ambiente.sh --skip-xmpp   # sem XMPP (Fase 0.3 pendente)
```

Ele imprime `[ OK ]`, `[AVISO]` e `[FALHA]` por item e um resumo final; o código
de saída é 0 somente quando não há falhas. Opções úteis: `--ipv6-iface`,
`--ipv6-peers "ip1 ip2"`, `--xmpp-host`, `--esperadas` (SAs IPSec esperadas,
padrão 3) e `--max-offset` (desvio NTP máximo, padrão 30 s — janela do
ReplayDefender). O `deploy_vms.sh` já o executa ao final de cada VM
(informativo); use `--skip-verificador` para omitir.

Para inspeção manual:

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
*   **Status das SAs IPSec (StrongSwan):**
    ```bash
    sudo ipsec statusall
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

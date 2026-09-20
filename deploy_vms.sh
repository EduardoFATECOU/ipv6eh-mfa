#!/bin/bash
# deploy_vms.sh - Script de implantação automatizada para ambiente 4 VMs

# Configurações - AJUSTE ESTAS VARIÁVEIS ANTES DE EXECUTAR
USER="ubuntu"
VM_CLIENT="192.168.1.10"
VM_SERVER="192.168.1.11"
VM_GATEWAY="192.168.1.12"
VM_AUDITOR="192.168.1.13"

# Mapeamento VM -> Serviço
declare -A SERVICES
SERVICES[$VM_CLIENT]="am"
SERVICES[$VM_SERVER]="am"
SERVICES[$VM_GATEWAY]="ad"
SERVICES[$VM_AUDITOR]="aa"

echo "Iniciando deploy nas VMs..."

for ip in "${!SERVICES[@]}"; do
    echo "--- Deploying to $ip (Service: ${SERVICES[$ip]}) ---"
    
    # 1. Copiar código
    ssh $USER@$ip "mkdir -p ~/ipv6eh-mfa"
    rsync -avz --exclude='.git' --exclude='data/' . $USER@$ip:~/ipv6eh-mfa/
    
    # 2. Instalar dependências
    ssh $USER@$ip "cd ~/ipv6eh-mfa && pip install -r requirements.txt"
    
    # 3. Configurar StrongSwan e Systemd
    scp ipsec/ipsec.conf ipsec/ipsec.secrets $USER@$ip:/etc/
    scp systemd/${SERVICES[$ip]}.service $USER@$ip:/tmp/
    
    ssh $USER@$ip "sudo mv /tmp/${SERVICES[$ip]}.service /etc/systemd/system/mfa-agent.service && \
                   sudo systemctl daemon-reload && \
                   sudo systemctl enable --now mfa-agent"
done

echo "Deploy concluído com sucesso."

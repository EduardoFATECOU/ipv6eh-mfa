#!/usr/bin/env bash
# deploy_vms.sh - Implantacao dos agentes nas 4 VMs (Fase 0.4 do CHECKLIST_EXPERIMENTOS.md)
#
# Uso:
#   ./deploy_vms.sh local [opcoes]     # SSH padrao (VirtualBox / hosts com chave ja configurada)
#   ./deploy_vms.sh aws   --key k.pem  # EC2 (AWS Academy) com chave .pem
#
# Opcoes:
#   --user <nome>       usuario SSH (padrao: ubuntu)
#   --key <arquivo>     chave .pem (obrigatoria no modo aws)
#   --hosts "<lista>"   IPs/hosts separados por espaco (padrao: 192.168.1.10..13)
#   --domain <dominio>  dominio XMPP (padrao: lars.local)
#   --dry-run           mostra o plano sem executar nada
#   --skip-deps         nao instala pacotes do sistema (apt)
#   -h, --help          ajuda
#
# Variaveis de ambiente equivalentes:
#   MFA_USER, MFA_KEY, MFA_HOSTS, MFA_DOMAIN, MFA_PASSWORD, MFA_AUDIT_KEY
#
# Papeis (ordem dos hosts): client, server, gateway, auditor
#   client  -> AM  (monitor1@dominio)
#   server  -> AM  (monitor2@dominio)
#   gateway -> AD  (decisor@dominio)
#   auditor -> AA  (auditor@dominio)

set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    MODO=""
else
    MODO="${1:-}"
    [[ -n "$MODO" ]] && shift
fi
[[ -z "$MODO" ]] || [[ "$MODO" == "aws" || "$MODO" == "local" ]] || {
    echo "erro: modo deve ser 'aws' ou 'local'" >&2
    echo "uso: $0 aws|local [opcoes]   (--help para detalhes)" >&2
    exit 2
}

USUARIO="${MFA_USER:-ubuntu}"
CHAVE="${MFA_KEY:-}"
DOMINIO="${MFA_DOMAIN:-lars.local}"
SENHA="${MFA_PASSWORD:-secret}"
AUDIT_DIR="${MFA_AUDIT_DIR:-/var/lib/mfa/logs}"
AUDIT_KEY="${MFA_AUDIT_KEY:-}"
HOSTS_STR="${MFA_HOSTS:-192.168.1.10 192.168.1.11 192.168.1.12 192.168.1.13}"
DRY_RUN=0
SKIP_DEPS=0
ARQUIVO_CHAVE_AUDIT=".mfa_audit_key"

ajuda() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)    USUARIO="$2"; shift 2 ;;
        --key)     CHAVE="$2"; shift 2 ;;
        --hosts)   HOSTS_STR="$2"; shift 2 ;;
        --domain)  DOMINIO="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --skip-deps) SKIP_DEPS=1; shift ;;
        -h|--help) ajuda; exit 0 ;;
        *) echo "erro: opcao desconhecida '$1'" >&2; exit 2 ;;
    esac
done

if [[ "$MODO" == "aws" && -z "$CHAVE" ]]; then
    echo "erro: modo aws exige --key <arquivo.pem> (ou MFA_KEY)" >&2
    exit 2
fi
if [[ "$MODO" == "aws" && ! -f "$CHAVE" ]]; then
    echo "erro: chave '$CHAVE' nao encontrada" >&2
    exit 2
fi

# shellcheck disable=SC2206
HOSTS=($HOSTS_STR)
if [[ ${#HOSTS[@]} -ne 4 ]]; then
    echo "erro: esperados 4 hosts (client server gateway auditor); recebidos ${#HOSTS[@]}" >&2
    exit 2
fi

PAPEIS=(client server gateway auditor)
SERVICOS=(am am ad aa)
MODULOS=(am_agent am_agent ad_agent aa_agent)
JIDS=(monitor1 monitor2 decisor auditor)

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o BatchMode=yes)
if [[ "$MODO" == "aws" ]]; then
    SSH_OPTS+=(-i "$CHAVE")
fi

passo() { echo "  - $*"; }

executar_ssh() {
    local host="$1"; shift
    if (( DRY_RUN )); then
        echo "    [dry-run] ssh $USUARIO@$host $*"
    else
        ssh "${SSH_OPTS[@]}" "$USUARIO@$host" "$@"
    fi
}

sincronizar() {
    local host="$1"
    local src
    src="$(cd "$(dirname "$0")" && pwd)/"
    local destino="$USUARIO@$host:~/ipv6eh-mfa/"
    if (( DRY_RUN )); then
        echo "    [dry-run] rsync -az $src -> $destino"
        return
    fi
    rsync -az --delete \
        --exclude '.git' --exclude 'data/' --exclude '__pycache__' \
        --exclude '.pytest_cache' --exclude '.venv' --exclude 'logs/' \
        -e "ssh ${SSH_OPTS[*]}" \
        "$src" "$destino"
}

escrever_env() {
    local host="$1" jid="$2" papel="$3"
    if (( DRY_RUN )); then
        echo "    [dry-run] escrever /etc/mfa/agent.env (MFA_JID=$jid@$DOMINIO)"
        return
    fi
    ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
        "sudo install -d -m 0755 /etc/mfa && sudo tee /etc/mfa/agent.env >/dev/null && sudo chmod 600 /etc/mfa/agent.env" <<EOF
# Gerado por deploy_vms.sh em $(date -u +%Y-%m-%dT%H:%M:%SZ)
MFA_JID=$jid@$DOMINIO
MFA_PASSWORD=$SENHA
MFA_LOG_LEVEL=INFO
MFA_AUTO_REGISTER=0
MFA_AD_JID=decisor@$DOMINIO
MFA_AA_JID=auditor@$DOMINIO
EOF
    if [[ "$papel" == "auditor" ]]; then
        ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
            "sudo tee -a /etc/mfa/agent.env >/dev/null" <<EOF
MFA_AUDIT_DIR=$AUDIT_DIR
MFA_AUDIT_KEY=$AUDIT_KEY
EOF
    fi
}

instalar_servico() {
    local host="$1" servico="$2"
    if (( DRY_RUN )); then
        echo "    [dry-run] instalar systemd/$servico.service como mfa-agent.service"
        return
    fi
    scp -q "${SSH_OPTS[@]}" "systemd/$servico.service" "$USUARIO@$host:/tmp/mfa-agent.service"
    ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
        "sudo mv /tmp/mfa-agent.service /etc/systemd/system/mfa-agent.service && \
         sudo systemctl daemon-reload && \
         sudo systemctl enable --now mfa-agent"
}

deploy_host() {
    local indice="$1" host="$2" papel="$3" servico="$4" jid="$5" modulo="$6"

    echo "[$indice/${#HOSTS[@]}] $host  papel=$papel  servico=$servico  jid=$jid@$DOMINIO"

    if (( ! DRY_RUN )); then
        if ! ssh "${SSH_OPTS[@]}" "$USUARIO@$host" true 2>/dev/null; then
            echo "  ERRO: SSH falhou em $host" >&2
            return 1
        fi
    fi

    passo "criar ~/ipv6eh-mfa"
    executar_ssh "$host" "mkdir -p ~/ipv6eh-mfa"

    passo "sincronizar codigo"
    sincronizar "$host"

    if (( ! SKIP_DEPS )); then
        passo "dependencias do sistema (apt)"
        executar_ssh "$host" "sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip rsync strongswan strongswan-pki chrony"
    fi

    passo "venv + requirements-vm.txt"
    executar_ssh "$host" "cd ~/ipv6eh-mfa && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements-vm.txt"

    passo "/etc/mfa/agent.env"
    escrever_env "$host" "$jid" "$papel"

    passo "servico systemd ($servico)"
    instalar_servico "$host" "$servico"

    passo "verificacao"
    if (( DRY_RUN )); then
        echo "    [dry-run] systemctl is-active mfa-agent && python -m $modulo --check"
    else
        ssh "${SSH_OPTS[@]}" "$USUARIO@$host" "systemctl is-active mfa-agent" || true
        executar_ssh "$host" "cd ~/ipv6eh-mfa && .venv/bin/python -m $modulo --check"
    fi
}

if (( ! DRY_RUN )); then
    if ! command -v rsync >/dev/null 2>&1; then
        echo "erro: rsync nao encontrado na maquina de controle" >&2
        exit 2
    fi
    if [[ -z "$AUDIT_KEY" ]]; then
        if [[ -f "$ARQUIVO_CHAVE_AUDIT" ]]; then
            AUDIT_KEY="$(cat "$ARQUIVO_CHAVE_AUDIT")"
        else
            AUDIT_KEY="$(openssl rand -hex 32)"
            printf '%s' "$AUDIT_KEY" > "$ARQUIVO_CHAVE_AUDIT"
            chmod 600 "$ARQUIVO_CHAVE_AUDIT"
            echo "chave HMAC do AA gerada em $ARQUIVO_CHAVE_AUDIT"
        fi
    fi
fi

echo "Deploy modo=$MODO hosts=${#HOSTS[@]} dominio=$DOMINIO dry_run=$DRY_RUN"
echo

falhas=0
for i in "${!HOSTS[@]}"; do
    if ! deploy_host "$((i + 1))" "${HOSTS[$i]}" "${PAPEIS[$i]}" "${SERVICOS[$i]}" "${JIDS[$i]}" "${MODULOS[$i]}"; then
        falhas=$((falhas + 1))
    fi
    echo
done

if (( falhas > 0 )); then
    echo "Deploy concluido com $falhas falha(s)." >&2
    exit 1
fi
echo "Deploy concluido com sucesso."

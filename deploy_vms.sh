#!/usr/bin/env bash
# deploy_vms.sh - Implantacao dos agentes nas 4 VMs (Fases 0.4 e 0.5)
#
# Uso:
#   ./deploy_vms.sh local [opcoes]     # SSH padrao (VirtualBox / hosts com chave ja configurada)
#   ./deploy_vms.sh aws   --key k.pem  # EC2 (AWS Academy) com chave .pem
#
# Opcoes:
#   --user <nome>       usuario SSH (padrao: ubuntu)
#   --key <arquivo>     chave .pem (obrigatoria no modo aws)
#   --hosts "<lista>"   IPs/hosts separados por espaco (padrao: 192.168.1.10..13)
#   --domain <dominio>  dominio XMPP/PKI (padrao: lars.local)
#   --ipv6-iface <dev>  configura os IPv6 2001:db8:* na interface indicada
#   --skip-deps         nao instala pacotes do sistema (apt)
#   --skip-ipsec        nao distribui PKI nem configura o StrongSwan
#   --dry-run           mostra o plano sem executar nada
#   -h, --help          ajuda
#
# Variaveis de ambiente equivalentes:
#   MFA_USER, MFA_KEY, MFA_HOSTS, MFA_DOMAIN, MFA_PASSWORD, MFA_AUDIT_KEY,
#   MFA_IPV6_IFACE
#
# Papeis (ordem dos hosts): client, server, gateway, auditor
#   client  -> AM  (monitor1@dominio)   cliente   2001:db8:1::10
#   server  -> AM  (monitor2@dominio)   servidor  2001:db8:2::11
#   gateway -> AD  (decisor@dominio)    gateway   2001:db8:2::12
#   auditor -> AA  (auditor@dominio)    auditor   2001:db8:2::13
#
# A PKI (ipsec/pki/) e gerada antes por ipsec/pki.sh; sem ela o IPSec e
# pulado com aviso e o restante do deploy continua.

set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"

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
IPV6_IFACE="${MFA_IPV6_IFACE:-}"
DRY_RUN=0
SKIP_DEPS=0
SKIP_IPSEC=0
AVISO_PKI=0
ARQUIVO_CHAVE_AUDIT=".mfa_audit_key"

ajuda() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)    USUARIO="$2"; shift 2 ;;
        --key)     CHAVE="$2"; shift 2 ;;
        --hosts)   HOSTS_STR="$2"; shift 2 ;;
        --domain)  DOMINIO="$2"; shift 2 ;;
        --ipv6-iface) IPV6_IFACE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        --skip-deps) SKIP_DEPS=1; shift ;;
        --skip-ipsec) SKIP_IPSEC=1; shift ;;
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
NOMES=(cliente servidor gateway auditor)
IPV6=(2001:db8:1::10 2001:db8:2::11 2001:db8:2::12 2001:db8:2::13)

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

copiar_arquivo() {
    local origem="$1" host="$2" destino="$3" modo="$4"
    local base
    base="$(basename "$destino")"
    scp -q "${SSH_OPTS[@]}" "$origem" "$USUARIO@$host:/tmp/$base"
    ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
        "sudo install -m $modo /tmp/$base $destino && rm -f /tmp/$base"
}

configurar_ipsec() {
    local host="$1" nome="$2"

    passo "certificados X.509 (PKI local)"
    if (( DRY_RUN )); then
        echo "    [dry-run] copiar ca-cert.pem e os 4 certificados para /etc/ipsec.d/certs/"
        echo "    [dry-run] copiar $nome-key.pem para /etc/ipsec.d/private/ (modo 600)"
        if [[ "$nome" == "auditor" ]]; then
            echo "    [dry-run] copiar ca-key.pem para /etc/ipsec.d/private/ (CA mantida pelo AA)"
        fi
        echo "    [dry-run] gerar /etc/ipsec.conf de $nome (transporte, 3 pares)"
        echo "    [dry-run] gravar /etc/ipsec.secrets e reiniciar strongswan"
        return 0
    fi

    if [[ ! -f "$AQUI/ipsec/pki/ca-cert.pem" ]]; then
        if (( AVISO_PKI == 0 )); then
            echo "    aviso: ipsec/pki/ca-cert.pem ausente; rode ipsec/pki.sh" >&2
            echo "    (o IPSec sera pulado nesta execucao)" >&2
            AVISO_PKI=1
        fi
        return 0
    fi

    ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
        "sudo install -d -m 0755 /etc/ipsec.d/cacerts /etc/ipsec.d/certs /etc/ipsec.d/private"

    copiar_arquivo "$AQUI/ipsec/pki/ca-cert.pem" "$host" \
        "/etc/ipsec.d/cacerts/ca-cert.pem" 644
    local j
    for j in "${!NOMES[@]}"; do
        copiar_arquivo "$AQUI/ipsec/pki/${NOMES[$j]}-cert.pem" "$host" \
            "/etc/ipsec.d/certs/${NOMES[$j]}-cert.pem" 644
    done
    copiar_arquivo "$AQUI/ipsec/pki/$nome-key.pem" "$host" \
        "/etc/ipsec.d/private/$nome-key.pem" 600
    if [[ "$nome" == "auditor" ]]; then
        # Cap. 7: a CA local e mantida pelo Agente de Auditoria (VM4).
        copiar_arquivo "$AQUI/ipsec/pki/ca-key.pem" "$host" \
            "/etc/ipsec.d/private/ca-key.pem" 600
    fi

    local tmp="$AQUI/ipsec/.ipsec.conf.$nome.tmp"
    bash "$AQUI/ipsec/gerar_conf.sh" --host "$nome" --domain "$DOMINIO" \
        --saida "$tmp" >/dev/null
    copiar_arquivo "$tmp" "$host" "/etc/ipsec.conf" 644
    rm -f "$tmp"

    ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
        "sudo tee /etc/ipsec.secrets >/dev/null && sudo chmod 600 /etc/ipsec.secrets" <<EOF
# Gerado por deploy_vms.sh
: ECDSA /etc/ipsec.d/private/$nome-key.pem
EOF

    executar_ssh "$host" \
        "sudo systemctl restart strongswan-starter 2>/dev/null || sudo systemctl restart strongswan"
}

deploy_host() {
    local i="$1"
    local host="${HOSTS[$i]}" papel="${PAPEIS[$i]}" servico="${SERVICOS[$i]}"
    local jid="${JIDS[$i]}" modulo="${MODULOS[$i]}" nome="${NOMES[$i]}" ipv6="${IPV6[$i]}"
    local indice=$((i + 1))

    echo "[$indice/${#HOSTS[@]}] $host  papel=$papel  nome=$nome  servico=$servico  jid=$jid@$DOMINIO"

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

    if [[ -n "$IPV6_IFACE" ]]; then
        passo "endereco IPv6 $ipv6/64 em $IPV6_IFACE"
        executar_ssh "$host" "sudo ip -6 addr replace $ipv6/64 dev $IPV6_IFACE"
    fi

    passo "venv + requirements-vm.txt"
    executar_ssh "$host" "cd ~/ipv6eh-mfa && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements-vm.txt"

    passo "/etc/mfa/agent.env"
    escrever_env "$host" "$jid" "$papel"

    passo "servico systemd ($servico)"
    instalar_servico "$host" "$servico"

    if (( ! SKIP_IPSEC )); then
        configurar_ipsec "$host" "$nome"
    fi

    passo "verificacao"
    if (( DRY_RUN )); then
        echo "    [dry-run] systemctl is-active mfa-agent && python -m $modulo --check"
        if (( ! SKIP_IPSEC )); then
            echo "    [dry-run] sudo ipsec statusall"
        fi
    else
        ssh "${SSH_OPTS[@]}" "$USUARIO@$host" "systemctl is-active mfa-agent" || true
        executar_ssh "$host" "cd ~/ipv6eh-mfa && .venv/bin/python -m $modulo --check"
        if (( ! SKIP_IPSEC )) && [[ -f "$AQUI/ipsec/pki/ca-cert.pem" ]]; then
            ssh "${SSH_OPTS[@]}" "$USUARIO@$host" \
                "sudo ipsec statusall 2>/dev/null | head -20" || true
        fi
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
    if ! deploy_host "$i"; then
        falhas=$((falhas + 1))
    fi
    echo
done

if (( falhas > 0 )); then
    echo "Deploy concluido com $falhas falha(s)." >&2
    exit 1
fi
echo "Deploy concluido com sucesso."

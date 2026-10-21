#!/usr/bin/env bash
# verificar_ambiente.sh - auditoria do ambiente das VMs (Fase 0.7)
#
# Executa em cada VM depois do deploy e confere se o ambiente esta pronto para
# os experimentos: sistema, dependencias Python, servico do agente, IPv6,
# sincronismo (NTP), SAs IPSec e servidor XMPP.
#
# O codigo de saida e 0 somente se nenhuma verificacao falhar; avisos nao
# reprovam o ambiente.
#
# Uso:
#   bash verificar_ambiente.sh                 # tudo (auto-detecta interface)
#   sudo bash verificar_ambiente.sh            # recomendado (le /etc/mfa e IPSec)
#   bash verificar_ambiente.sh --skip-xmpp     # sem o teste XMPP (Fase 0.3 pendente)
#   bash verificar_ambiente.sh --ipv6-iface enp0s8 --ipv6-peers "2001:db8:2::11"
#
# Opcoes:
#   --projeto <dir>        raiz do projeto (padrao: diretorio do script)
#   --ipv6-iface <dev>     interface IPv6 a auditar (padrao: qualquer uma)
#   --ipv6-peers "<ips>"   peers para ping6 (padrao: as 4 VMs; ignora a local)
#   --xmpp-host <host>     servidor XMPP (padrao: 192.168.1.13)
#   --xmpp-port <porta>    porta XMPP (padrao: 5222)
#   --esperadas <n>        SAs IPSec esperadas (padrao: 3)
#   --max-offset <s>       desvio NTP maximo em segundos (padrao: 30)
#   --skip-sistema --skip-deps --skip-agente --skip-ipv6
#   --skip-ntp --skip-ipsec --skip-xmpp
#   -h, --help             ajuda
#
# Enderecos padrao das VMs:
#   cliente  2001:db8:1::10   192.168.1.10
#   servidor 2001:db8:2::11   192.168.1.11
#   gateway  2001:db8:2::12   192.168.1.12
#   auditor  2001:db8:2::13   192.168.1.13

set -uo pipefail
export LC_ALL=C

AQUI="$(cd "$(dirname "$0")" && pwd)"
PROJETO="$AQUI"
IPV6_IFACE=""
IPV6_PEERS="2001:db8:1::10 2001:db8:2::11 2001:db8:2::12 2001:db8:2::13"
XMPP_HOST="${MFA_XMPP_HOST:-192.168.1.13}"
XMPP_PORT="${MFA_XMPP_PORT:-5222}"
ESPERADAS=3
MAX_OFFSET=30

SKIP_SISTEMA=0
SKIP_DEPS=0
SKIP_AGENTE=0
SKIP_IPV6=0
SKIP_NTP=0
SKIP_IPSEC=0
SKIP_XMPP=0

OK=0
AVISOS=0
FALHAS=0

ajuda() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

precisa_valor() {
    if [[ $# -lt 2 ]]; then
        echo "erro: $1 exige um valor" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --projeto|--ipv6-iface|--ipv6-peers|--xmpp-host|--xmpp-port|--esperadas|--max-offset)
            precisa_valor "$@" ;;
    esac
    case "$1" in
        --projeto)      PROJETO="$2"; shift 2 ;;
        --ipv6-iface)   IPV6_IFACE="$2"; shift 2 ;;
        --ipv6-peers)   IPV6_PEERS="$2"; shift 2 ;;
        --xmpp-host)    XMPP_HOST="$2"; shift 2 ;;
        --xmpp-port)    XMPP_PORT="$2"; shift 2 ;;
        --esperadas)    ESPERADAS="$2"; shift 2 ;;
        --max-offset)   MAX_OFFSET="$2"; shift 2 ;;
        --skip-sistema) SKIP_SISTEMA=1; shift ;;
        --skip-deps)    SKIP_DEPS=1; shift ;;
        --skip-agente)  SKIP_AGENTE=1; shift ;;
        --skip-ipv6)    SKIP_IPV6=1; shift ;;
        --skip-ntp)     SKIP_NTP=1; shift ;;
        --skip-ipsec)   SKIP_IPSEC=1; shift ;;
        --skip-xmpp)    SKIP_XMPP=1; shift ;;
        -h|--help)      ajuda; exit 0 ;;
        *) echo "erro: opcao desconhecida '$1'" >&2; exit 2 ;;
    esac
done

if (( SKIP_SISTEMA + SKIP_DEPS + SKIP_AGENTE + SKIP_IPV6 + SKIP_NTP + SKIP_IPSEC + SKIP_XMPP == 7 )); then
    echo "erro: todas as verificacoes foram desativadas (nada a fazer)" >&2
    exit 2
fi

ok()      { OK=$((OK + 1)); printf '  [ OK ] %s\n' "$*"; }
aviso()   { AVISOS=$((AVISOS + 1)); printf '  [AVISO] %s\n' "$*"; }
falha()   { FALHAS=$((FALHAS + 1)); printf '  [FALHA] %s\n' "$*"; }
detalhe() { printf '          %s\n' "$*"; }
secao()   { printf '\n== %s ==\n' "$*"; }

SUDO=""
if (( EUID != 0 )) && command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    SUDO="sudo -n"
fi

# Escolhe o primeiro interpretador que realmente executa (o stub python3 do
# Windows, por exemplo, existe no PATH mas falha ao iniciar).
escolher_python() {
    local cand
    for cand in "$PROJETO/.venv/bin/python" "$(command -v python3 2>/dev/null)" \
                "$(command -v python 2>/dev/null)"; do
        [[ -n "$cand" && -x "$cand" ]] || continue
        if "$cand" -c 'import sys' >/dev/null 2>&1; then
            printf '%s' "$cand"
            return 0
        fi
    done
    return 1
}

python_bin="$(escolher_python || true)"
eh_linux=0
[[ "$(uname -s 2>/dev/null)" == "Linux" ]] && eh_linux=1

printf 'Verificacao do ambiente MFA/IPv6 (Fase 0.7)\n'
printf 'Host: %s | Projeto: %s | Data: %s\n' \
    "$(hostname 2>/dev/null || echo '?')" "$PROJETO" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --------------------------------------------------------------------------
# 1. Sistema
# --------------------------------------------------------------------------
if (( ! SKIP_SISTEMA )); then
    secao "Sistema"
    if [[ "$eh_linux" == 1 ]]; then
        ok "$( . /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-Linux}" ) (kernel $(uname -r 2>/dev/null))"
    else
        aviso "sistema $(uname -s 2>/dev/null)/$(uname -r 2>/dev/null) (esperado Linux; rode na VM)"
    fi

    if [[ -z "$python_bin" ]]; then
        falha "Python nao encontrado (esperado 3.10+)"
    else
        versao="$("$python_bin" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)"
        if "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            ok "Python $versao ($python_bin)"
        else
            falha "Python $versao < 3.10 ($python_bin)"
        fi
    fi

    if [[ "$eh_linux" == 1 && -r /proc/meminfo ]]; then
        ram_mb="$(awk '/^MemTotal:/ { print int($2 / 1024) }' /proc/meminfo)"
        if [[ -n "$ram_mb" ]]; then
            if (( ram_mb < 6144 )); then
                aviso "RAM total ${ram_mb} MB (< 6 GB; especificacao da tese: 8 GB)"
            else
                ok "RAM total ${ram_mb} MB"
            fi
        fi
    fi

    if [[ "$eh_linux" == 1 ]] && command -v df >/dev/null 2>&1; then
        livre_kb="$(df -Pk "$PROJETO" 2>/dev/null | awk 'NR == 2 { print $4 }')"
        if [[ -n "${livre_kb:-}" ]]; then
            livre_gb=$((livre_kb / 1024 / 1024))
            if (( livre_gb < 5 )); then
                aviso "disco livre ${livre_gb} GB em $PROJETO (< 5 GB)"
            else
                ok "disco livre ${livre_gb} GB"
            fi
        fi
    fi
fi

# --------------------------------------------------------------------------
# 2. Dependencias Python
# --------------------------------------------------------------------------
if (( ! SKIP_DEPS )); then
    secao "Dependencias Python"
    if [[ -z "$python_bin" ]]; then
        falha "sem interpretador Python para testar as dependencias"
    else
        faltando="$("$python_bin" - <<'PY' 2>/dev/null
import importlib.util

mods = ["spade", "scapy", "sklearn", "river", "psutil", "tensorflow"]
print(" ".join(m for m in mods if importlib.util.find_spec(m) is None))
PY
)"
        if [[ -n "$faltando" ]]; then
            falha "modulos ausentes: $faltando"
            detalhe "instale com: .venv/bin/pip install -r requirements-vm.txt"
        else
            ok "spade, scapy, sklearn, river, psutil e tensorflow instalados"
        fi
    fi
fi

# --------------------------------------------------------------------------
# 3. Agente (systemd + /etc/mfa/agent.env)
# --------------------------------------------------------------------------
if (( ! SKIP_AGENTE )); then
    secao "Agente"
    arquivo_env="/etc/mfa/agent.env"
    conteudo=""
    if [[ -r "$arquivo_env" ]]; then
        conteudo="$(cat "$arquivo_env")"
    elif [[ -n "$SUDO" ]] && $SUDO test -r "$arquivo_env"; then
        conteudo="$($SUDO cat "$arquivo_env")"
    fi

    jid=""
    if [[ -n "$conteudo" ]]; then
        jid="$(printf '%s\n' "$conteudo" | sed -n 's/^MFA_JID=//p' | head -1)"
        if [[ -n "$jid" ]]; then
            ok "$arquivo_env presente (MFA_JID=$jid)"
        else
            falha "$arquivo_env sem MFA_JID"
        fi
    else
        falha "$arquivo_env ausente ou sem permissao de leitura (rode com sudo)"
    fi

    if command -v systemctl >/dev/null 2>&1; then
        estado="$(systemctl is-active mfa-agent 2>/dev/null || true)"
        if [[ "$estado" == "active" ]]; then
            ok "servico mfa-agent ativo"
        else
            falha "servico mfa-agent estado='${estado:-desconhecido}'"
            detalhe "journalctl -u mfa-agent -e"
        fi

        unidade="/etc/systemd/system/mfa-agent.service"
        texto_unidade=""
        if [[ -r "$unidade" ]]; then
            texto_unidade="$(cat "$unidade")"
        elif [[ -n "$SUDO" ]] && $SUDO test -r "$unidade"; then
            texto_unidade="$($SUDO cat "$unidade")"
        fi

        if [[ -n "$texto_unidade" ]]; then
            modulo="$(printf '%s\n' "$texto_unidade" | sed -n 's/.*-m \([a-z_][a-z_]*\).*/\1/p' | head -1)"
            if [[ -n "$modulo" && -n "$jid" && -n "$python_bin" ]]; then
                if ( cd "$PROJETO" && MFA_JID="$jid" "$python_bin" -m "$modulo" --check >/dev/null 2>&1 ); then
                    ok "python -m $modulo --check"
                else
                    falha "python -m $modulo --check retornou erro"
                fi
            else
                aviso "modulo do agente nao identificado (ou MFA_JID ausente)"
            fi
        else
            aviso "$unidade nao encontrado"
        fi
    else
        aviso "systemd indisponivel (fora da VM?)"
    fi
fi

# --------------------------------------------------------------------------
# 4. IPv6 (endereco local + alcance dos peers)
# --------------------------------------------------------------------------
locais=""
if (( ! SKIP_IPV6 )); then
    secao "IPv6"
    if ! command -v ip >/dev/null 2>&1; then
        falha "comando 'ip' (iproute2) nao encontrado"
    else
        if [[ -n "$IPV6_IFACE" ]]; then
            locais="$(ip -6 -o addr show dev "$IPV6_IFACE" scope global 2>/dev/null | awk '{ print $4 }' | cut -d/ -f1)"
        else
            locais="$(ip -6 -o addr show scope global 2>/dev/null | awk '{ print $4 }' | cut -d/ -f1)"
        fi
        if [[ -n "$locais" ]]; then
            ok "enderecos IPv6: $(printf '%s' "$locais" | tr '\n' ' ')"
        else
            falha "nenhum endereco IPv6 global${IPV6_IFACE:+ em $IPV6_IFACE}"
            detalhe "use --ipv6-iface <dev> ou configure 2001:db8:* (deploy --ipv6-iface)"
        fi
    fi

    PING6=()
    if command -v ping6 >/dev/null 2>&1; then
        PING6=(ping6)
    elif command -v ping >/dev/null 2>&1 && ping -6 -c 1 -W 1 ::1 >/dev/null 2>&1; then
        PING6=(ping -6)
    fi

    if [[ -z "$IPV6_PEERS" ]]; then
        aviso "nenhum peer IPv6 informado (--ipv6-peers vazio)"
    elif [[ ${#PING6[@]} -eq 0 ]]; then
        falha "ping6 indisponivel para testar os peers"
    else
        for peer in $IPV6_PEERS; do
            if printf '%s\n' "$locais" | grep -qx "$peer"; then
                continue
            fi
            if "${PING6[@]}" -c 2 -W 2 "$peer" >/dev/null 2>&1; then
                ok "ping6 $peer"
            else
                falha "ping6 $peer sem resposta"
            fi
        done
    fi
fi

# --------------------------------------------------------------------------
# 5. NTP (janela de 30 s do ReplayDefender)
# --------------------------------------------------------------------------
if (( ! SKIP_NTP )); then
    secao "Sincronismo (NTP)"
    offset=""
    if command -v chronyc >/dev/null 2>&1; then
        saida_chrony="$($SUDO chronyc tracking 2>/dev/null || chronyc tracking 2>/dev/null || true)"
        offset="$(printf '%s\n' "$saida_chrony" | awk -F: '/^System time/ { print $2 }' | awk '{ print $1 }')"
        if [[ -n "$offset" ]]; then
            if awk -v o="$offset" -v m="$MAX_OFFSET" 'BEGIN { exit !((o < 0 ? -o : o) <= m) }'; then
                ok "desvio do relogio ${offset}s (limite ${MAX_OFFSET}s)"
            else
                falha "desvio do relogio ${offset}s > ${MAX_OFFSET}s (C3 depende de relogios sincronizados)"
            fi
        else
            aviso "chronyc nao retornou 'System time' (chronyd parado?)"
        fi
    elif command -v timedatectl >/dev/null 2>&1; then
        sincronizado="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
        if [[ "$sincronizado" == "yes" ]]; then
            ok "relogio sincronizado (timedatectl)"
        else
            falha "relogio nao sincronizado (timedatectl NTPSynchronized=${sincronizado:-?})"
        fi
    else
        falha "nem chronyc nem timedatectl disponiveis"
    fi

    if command -v systemctl >/dev/null 2>&1; then
        estado_ntp="$(systemctl is-active chrony 2>/dev/null || true)"
        if [[ "$estado_ntp" == "active" ]]; then
            ok "servico chrony ativo"
        else
            aviso "servico chrony estado='${estado_ntp:-desconhecido}'"
        fi
    fi
fi

# --------------------------------------------------------------------------
# 6. IPSec (SAs em modo transporte)
# --------------------------------------------------------------------------
if (( ! SKIP_IPSEC )); then
    secao "IPSec"
    if ! command -v ipsec >/dev/null 2>&1; then
        falha "comando 'ipsec' nao encontrado (apt install strongswan)"
    else
        status_ipsec="$($SUDO ipsec statusall 2>/dev/null || true)"
        if [[ -z "$status_ipsec" ]]; then
            falha "ipsec statusall sem saida (precisa de root: rode com sudo)"
        else
            estabelecidas="$(printf '%s\n' "$status_ipsec" | grep -c 'ESTABLISHED')"
            if (( estabelecidas >= ESPERADAS )); then
                ok "$estabelecidas de $ESPERADAS SAs ESTABLISHED"
            else
                falha "$estabelecidas de $ESPERADAS SAs ESTABLISHED"
                detalhe "ipsec statusall | grep -E 'ESTABLISHED|INSTALLED'"
            fi

            if printf '%s\n' "$status_ipsec" | grep -q 'INSTALLED'; then
                ok "CHILD_SAs instaladas (ESP ativo)"
            else
                falha "nenhuma CHILD_SA instalada"
            fi
        fi

        conf="/etc/ipsec.conf"
        segredos="/etc/ipsec.secrets"
        if [[ -r "$conf" ]] || { [[ -n "$SUDO" ]] && $SUDO test -r "$conf"; }; then
            ok "$conf presente"
        else
            falha "$conf ausente"
        fi
        if [[ -r "$segredos" ]] || { [[ -n "$SUDO" ]] && $SUDO test -r "$segredos"; }; then
            modo="$($SUDO stat -c '%a' "$segredos" 2>/dev/null || stat -c '%a' "$segredos" 2>/dev/null || echo '?')"
            if [[ "$modo" == "600" ]]; then
                ok "$segredos com permissao 600"
            else
                falha "$segredos com permissao $modo (esperado 600)"
            fi
        else
            falha "$segredos ausente"
        fi

        chaves="$($SUDO sh -c 'ls /etc/ipsec.d/private/*-key.pem 2>/dev/null' || true)"
        if [[ -n "$chaves" ]]; then
            inseguras="$($SUDO sh -c 'find /etc/ipsec.d/private -name "*-key.pem" ! -perm 600 -print' 2>/dev/null || true)"
            if [[ -z "$inseguras" ]]; then
                ok "chaves privadas em /etc/ipsec.d/private com permissao 600"
            else
                falha "chaves com permissao incorreta: $inseguras"
            fi
        else
            aviso "nenhuma chave *-key.pem em /etc/ipsec.d/private (rode o deploy com PKI)"
        fi
    fi
fi

# --------------------------------------------------------------------------
# 7. XMPP (Prosody na VM4)
# --------------------------------------------------------------------------
if (( ! SKIP_XMPP )); then
    secao "XMPP"
    if [[ -z "$python_bin" ]]; then
        falha "sem Python para testar a porta XMPP"
    elif "$python_bin" -c 'import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(3)
sys.exit(0 if s.connect_ex((sys.argv[1], int(sys.argv[2]))) == 0 else 1)' "$XMPP_HOST" "$XMPP_PORT" >/dev/null 2>&1; then
        ok "TCP $XMPP_HOST:$XMPP_PORT acessivel (login XMPP nao testado)"
    else
        falha "TCP $XMPP_HOST:$XMPP_PORT inacessivel"
        detalhe "verifique o Prosody na VM4 e o Security Group (Fase 0.3)"
    fi
fi

# --------------------------------------------------------------------------
# Resumo
# --------------------------------------------------------------------------
printf '\nResumo: %d OK, %d aviso(s), %d falha(s)\n' "$OK" "$AVISOS" "$FALHAS"
if (( FALHAS > 0 )); then
    echo "Ambiente NAO esta pronto para os experimentos."
    exit 1
fi
echo "Ambiente pronto para os experimentos."
exit 0

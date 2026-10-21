#!/usr/bin/env bash
# gerar_conf.sh - renderiza o /etc/ipsec.conf de uma VM (Fase 0.5).
#
# Le ipsec/ipsec.conf (template), substitui os campos da VM local e gera uma
# conexao em modo transporte para cada par. Chamado pelo deploy_vms.sh.
#
# Uso:
#   ./gerar_conf.sh --host cliente                 # tabela padrao (4 VMs)
#   ./gerar_conf.sh --host cliente --saida /tmp/ipsec.conf
#   ./gerar_conf.sh --host vm5 --ipv6 2001:db8:9::5 \
#                   --peers "cliente=2001:db8:1::10 gateway=2001:db8:2::12"
#
# Tabela padrao (mesma do deploy_vms.sh):
#   cliente  2001:db8:1::10
#   servidor 2001:db8:2::11
#   gateway  2001:db8:2::12
#   auditor  2001:db8:2::13

set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE="$AQUI/ipsec.conf"
DOMINIO="lars.local"
NOMES=(cliente servidor gateway auditor)
IPS=(2001:db8:1::10 2001:db8:2::11 2001:db8:2::12 2001:db8:2::13)
NOME=""
IPV6=""
PEERS=""
SAIDA=""

ajuda() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)     NOME="$2"; shift 2 ;;
        --ipv6)     IPV6="$2"; shift 2 ;;
        --peers)    PEERS="$2"; shift 2 ;;
        --domain)   DOMINIO="$2"; shift 2 ;;
        --template) TEMPLATE="$2"; shift 2 ;;
        --saida)    SAIDA="$2"; shift 2 ;;
        -h|--help)  ajuda; exit 0 ;;
        *) echo "erro: opcao desconhecida '$1'" >&2; exit 2 ;;
    esac
done

if [[ -z "$NOME" ]]; then
    echo "erro: informe --host <nome>" >&2
    exit 2
fi
if [[ ! -f "$TEMPLATE" ]]; then
    echo "erro: template nao encontrado: $TEMPLATE" >&2
    exit 2
fi

# Resolve o IP local e os pares pela tabela padrao quando o host e conhecido.
indice_local=-1
for i in "${!NOMES[@]}"; do
    if [[ "${NOMES[$i]}" == "$NOME" ]]; then
        indice_local=$i
        break
    fi
done

if [[ -n "$IPV6" && -n "$PEERS" ]]; then
    :  # modo explicito
elif (( indice_local >= 0 )); then
    [[ -n "$IPV6" ]] || IPV6="${IPS[$indice_local]}"
    if [[ -z "$PEERS" ]]; then
        partes=()
        for i in "${!NOMES[@]}"; do
            (( i == indice_local )) && continue
            partes+=("${NOMES[$i]}=${IPS[$i]}")
        done
        PEERS="${partes[*]}"
    fi
else
    echo "erro: host '$NOME' fora da tabela padrao; informe --ipv6 e --peers" >&2
    exit 2
fi

if [[ -z "$IPV6" || -z "$PEERS" ]]; then
    echo "erro: --ipv6 e --peers sao obrigatorios para hosts fora da tabela" >&2
    exit 2
fi

# Cabecalho (tudo antes do marcador), com os campos da VM local resolvidos.
render() {
    awk '/^# >>> CONNS/ {exit} {print}' "$TEMPLATE" \
        | sed -e "s|@NOME@|$NOME|g" \
              -e "s|@IPV6@|$IPV6|g" \
              -e "s|@DOMINIO@|$DOMINIO|g"

    for par in $PEERS; do
        local pnome="${par%%=*}"
        local pip="${par#*=}"
        if [[ -z "$pnome" || "$pip" == "$par" || -z "$pip" ]]; then
            echo "erro: par invalido '$par' (use nome=ipv6)" >&2
            return 1
        fi
        [[ "$pnome" == "$NOME" ]] && continue
        printf '\nconn mfa-%s\n    right=%s\n    rightid=%s.%s\n    rightcert=/etc/ipsec.d/certs/%s-cert.pem\n' \
            "$pnome" "$pip" "$pnome" "$DOMINIO" "$pnome"
    done

    printf '\n# Gerado por ipsec/gerar_conf.sh: local=%s (%s), pares: %s\n' \
        "$NOME" "$IPV6" "$(echo "$PEERS" | tr ' ' ',')"
}

if [[ -n "$SAIDA" ]]; then
    render > "$SAIDA"
    echo "ipsec.conf de $NOME ($IPV6) -> $SAIDA"
else
    render
fi

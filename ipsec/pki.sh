#!/usr/bin/env bash
# pki.sh - gera a CA local e os 4 certificados ECDSA P-256 (Fase 0.5).
#
# Executa na MAQUINA DE CONTROLE (nao precisa de root e nao escreve em /etc):
# os arquivos vao para ipsec/pki/ e o deploy_vms.sh os distribui nas VMs.
# A chave da CA e instalada apenas na VM4 (AA), que mantem a autoridade
# certificadora do ambiente (Cap. 7); as demais VMs recebem so o certificado.
#
# Pre-requisito: strongswan-pki (`apt install strongswan-pki`). No Windows,
# rode dentro do WSL/Ubuntu.
#
# Uso:
#   ./pki.sh                 # gera ipsec/pki/ (falha se ja existir)
#   ./pki.sh --force         # regera (sobrescreve a CA e os certificados)
#   ./pki.sh --dry-run       # mostra os comandos sem executar
#
# Saida em ipsec/pki/:
#   ca-key.pem  ca-cert.pem
#   cliente-{key,pub,cert}.pem     (VM1, 2001:db8:1::10)
#   servidor-{key,pub,cert}.pem    (VM2, 2001:db8:2::11)
#   gateway-{key,pub,cert}.pem     (VM3, 2001:db8:2::12)
#   auditor-{key,pub,cert}.pem     (VM4, 2001:db8:2::13)
#   SHA256SUMS
#
# Os nomes/IPs podem ser trocados por flags (ver --help).

set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
SAIDA="$AQUI/pki"
DOMINIO="lars.local"
NOMES_PADRAO="cliente servidor gateway auditor"
IPS_PADRAO="2001:db8:1::10 2001:db8:2::11 2001:db8:2::12 2001:db8:2::13"
NOMES_STR="$NOMES_PADRAO"
IPS_STR="$IPS_PADRAO"
FORCAR=0
DRY_RUN=0

ajuda() {
    sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dir)     SAIDA="$2"; shift 2 ;;
        --domain)  DOMINIO="$2"; shift 2 ;;
        --hosts)   NOMES_STR="$2"; shift 2 ;;
        --ips)     IPS_STR="$2"; shift 2 ;;
        --force)   FORCAR=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) ajuda; exit 0 ;;
        *) echo "erro: opcao desconhecida '$1'" >&2; exit 2 ;;
    esac
done

# shellcheck disable=SC2206
NOMES=($NOMES_STR)
# shellcheck disable=SC2206
IPS=($IPS_STR)

if [[ ${#NOMES[@]} -ne 4 || ${#IPS[@]} -ne 4 ]]; then
    echo "erro: informe 4 nomes e 4 IPv6 (ex.: --hosts \"cliente servidor gateway auditor\")" >&2
    exit 2
fi

if (( ! DRY_RUN )) && ! command -v ipsec >/dev/null 2>&1; then
    echo "erro: 'ipsec' nao encontrado. Instale strongswan-pki (apt install strongswan-pki)." >&2
    exit 2
fi

if (( ! DRY_RUN && ! FORCAR )); then
    for arquivo in ca-key.pem ca-cert.pem; do
        if [[ -f "$SAIDA/$arquivo" ]]; then
            echo "erro: $SAIDA/$arquivo ja existe (use --force para regerar a CA)" >&2
            exit 2
        fi
    done
fi

echo "PKI: saida=$SAIDA dominio=$DOMINIO hosts=${NOMES[*]}"
(( DRY_RUN )) && echo "(dry-run: nenhum arquivo sera escrito)"

if (( ! DRY_RUN )); then
    mkdir -p "$SAIDA"
    chmod 700 "$SAIDA"
    umask 077
fi

# 1) CA local (ECDSA P-256, 10 anos)
echo "- CA: ca-key.pem / ca-cert.pem"
if (( DRY_RUN )); then
    echo "    [dry-run] ipsec pki --gen --type ecdsa --size 256 --outform pem > $SAIDA/ca-key.pem"
    echo "    [dry-run] ipsec pki --self --ca --lifetime 3650 --in $SAIDA/ca-key.pem \\"
    echo "              --dn \"C=BR, O=LARS/UNESP, CN=CA-lars\" --outform pem > $SAIDA/ca-cert.pem"
else
    ipsec pki --gen --type ecdsa --size 256 --outform pem > "$SAIDA/ca-key.pem"
    ipsec pki --self --ca --lifetime 3650 \
        --in "$SAIDA/ca-key.pem" \
        --dn "C=BR, O=LARS/UNESP, CN=CA-lars" \
        --outform pem > "$SAIDA/ca-cert.pem"
    chmod 644 "$SAIDA/ca-cert.pem"
fi

# 2) Certificados das 4 VMs (ECDSA P-256, 3 anos, SAN = FQDN + IPv6)
for i in "${!NOMES[@]}"; do
    nome="${NOMES[$i]}"
    ip="${IPS[$i]}"
    fqdn="$nome.$DOMINIO"
    echo "- $nome ($fqdn, $ip)"
    if (( DRY_RUN )); then
        echo "    [dry-run] ipsec pki --gen --type ecdsa --size 256 --outform pem > $SAIDA/$nome-key.pem"
        echo "    [dry-run] ipsec pki --pub --in $SAIDA/$nome-key.pem --outform pem > $SAIDA/$nome-pub.pem"
        echo "    [dry-run] ipsec pki --issue --lifetime 1095 --cacert $SAIDA/ca-cert.pem \\"
        echo "              --cakey $SAIDA/ca-key.pem --in $SAIDA/$nome-pub.pem \\"
        echo "              --dn \"C=BR, O=LARS/UNESP, CN=$fqdn\" --san $fqdn --san $ip \\"
        echo "              --flag serverAuth --flag clientAuth --outform pem > $SAIDA/$nome-cert.pem"
    else
        ipsec pki --gen --type ecdsa --size 256 --outform pem > "$SAIDA/$nome-key.pem"
        ipsec pki --pub --in "$SAIDA/$nome-key.pem" --outform pem > "$SAIDA/$nome-pub.pem"
        ipsec pki --issue --lifetime 1095 \
            --cacert "$SAIDA/ca-cert.pem" \
            --cakey "$SAIDA/ca-key.pem" \
            --in "$SAIDA/$nome-pub.pem" \
            --dn "C=BR, O=LARS/UNESP, CN=$fqdn" \
            --san "$fqdn" --san "$ip" \
            --flag serverAuth --flag clientAuth \
            --outform pem > "$SAIDA/$nome-cert.pem"
        chmod 644 "$SAIDA/$nome-cert.pem" "$SAIDA/$nome-pub.pem"
    fi
done

# 3) Inventario para conferencia (fingerprints das chaves publicas/certs)
if (( DRY_RUN )); then
    echo "- [dry-run] sha256sum *.pem > $SAIDA/SHA256SUMS"
else
    ( cd "$SAIDA" && sha256sum -- *.pem > SHA256SUMS )
    echo
    echo "OK: $(ls "$SAIDA"/*.pem | wc -l) arquivos em $SAIDA"
    echo "Proximo passo: ./deploy_vms.sh local   (distribui a PKI e o ipsec.conf)"
fi

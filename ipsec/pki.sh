# Template de certificados/PKI para o StrongSwan (ambiente 4 VMs).

# 1) Autoridade Certificadora (CA)
ipsec pki --gen --type ecdsa --size 256 --outform der > /etc/ipsec.d/private/ca-key.der
ipsec pki --self --ca --lifetime 3650 \
    --in /etc/ipsec.d/private/ca-key.der --type rsa-sig \
    --dn "C=BR, O=LARS/UNESP, CN=CA-lars" \
    --outform der > /etc/ipsec.d/cacerts/ca-cert.der

# 2) Certificados de cada VM (cliente/servidor)
HOSTS=(cliente servidor)
for h in "${HOSTS[@]}"; do
  ipsec pki --gen --type ecdsa --size 256 --outform der > /etc/ipsec.d/private/${h}-key.der
  ipsec pki --pub --in /etc/ipsec.d/private/${h}-key.der --type rsa-sig \
      | ipsec pki --issue --lifetime 1095 --cacert /etc/ipsec.d/cacerts/ca-cert.der \
        --cakey /etc/ipsec.d/private/ca-key.der \
        --dn "C=BR, O=LARS/UNESP, CN=${h}.lars.unesp.br" \
        --san "${h}.lars.unesp.br" \
        --flag serverAuth --flag ikeIntermediate \
        --outform der > /etc/ipsec.d/certs/${h}-cert.der
done

# 3) Referenciar os certificados no ipsec.conf:
#    leftcert=cliente-cert.der   /   rightcert=servidor-cert.der

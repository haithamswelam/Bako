#!/usr/bin/env bash
# install-externaldns.sh - installs ExternalDNS in the cluster (called by bootstrap-cluster.sh after the ALB controller).
# ExternalDNS watches the Ingress. When the ALB appears it writes  bako.awsbako.site -> ALB  into Route 53 (alias record);
# when the Ingress is deleted (pre-destroy-alb.sh) it removes the record again (policy=sync, only records it owns).
set -euo pipefail
unset KUBECONFIG
CLUSTER_NAME="${CLUSTER_NAME:-bako-eks}"
REGION="${REGION:-eu-north-1}"
DOMAIN="${DOMAIN:-bako.awsbako.site}"
DNS_ROLE_NAME="${DNS_ROLE_NAME:-bako-external-dns-irsa-role}"
# Empty = newest chart. The script prints the version it installed: write it here once it works, so it never changes by surprise.
EXTERNALDNS_CHART_VERSION="${EXTERNALDNS_CHART_VERSION:-}"

echo "== ExternalDNS: look up the IAM role (made by terraform, external-dns.tf) =="
DNS_ROLE_ARN=$(aws iam get-role --role-name "$DNS_ROLE_NAME" --query "Role.Arn" --output text)

echo "== ExternalDNS: helm repo =="
helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/ >/dev/null 2>&1 || true
helm repo update external-dns >/dev/null

VER_ARGS=()
[ -n "$EXTERNALDNS_CHART_VERSION" ] && VER_ARGS=(--version "$EXTERNALDNS_CHART_VERSION")

echo "== ExternalDNS: install =="
helm upgrade --install external-dns external-dns/external-dns \
  --namespace kube-system "${VER_ARGS[@]}" \
  --set provider.name=aws \
  --set "domainFilters[0]=${DOMAIN}" \
  --set "sources[0]=ingress" \
  --set policy=sync \
  --set registry=txt \
  --set txtOwnerId="${CLUSTER_NAME}" \
  --set "txtPrefix=externaldns-" \
  --set interval=30s \
  --set "env[0].name=AWS_DEFAULT_REGION" --set "env[0].value=${REGION}" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=external-dns \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"="$DNS_ROLE_ARN" \
  --wait --timeout 5m
kubectl rollout status deployment/external-dns -n kube-system --timeout=180s
echo "ExternalDNS chart installed: $(helm list -n kube-system -f '^external-dns$' -o json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["chart"] if d else "unknown")')"

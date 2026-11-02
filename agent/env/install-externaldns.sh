#!/usr/bin/env bash
# install-externaldns.sh - installs (SOURCED by bootstrap-cluster.sh, not run as a new bash: a new bash on Windows loses the PATH) ExternalDNS in the cluster (called by bootstrap-cluster.sh after the ALB controller).
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

# Deletes the records ExternalDNS made: A/AAAA at the domain name, and its TXT markers (names starting externaldns-).
# NS, SOA, the certificate CNAME and any other TXT record are never touched.
purge_dns_records() {
  local zone batch
  zone=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN" --max-items 1 \
    --query "HostedZones[?Name=='${DOMAIN}.'].Id | [0]" --output text 2>/dev/null) || return 0
  { [ -z "$zone" ] || [ "$zone" = "None" ]; } && return 0
  zone="${zone##*/}"
  batch=$(aws route53 list-resource-record-sets --hosted-zone-id "$zone" \
    --query "{Changes: ResourceRecordSets[?(Name=='${DOMAIN}.' && (Type=='A' || Type=='AAAA')) || (Type=='TXT' && starts_with(Name, 'externaldns-'))].{Action: 'DELETE', ResourceRecordSet: @}}" \
    --output json 2>/dev/null) || return 0
  case "$batch" in *'"Action"'*) ;; *) return 0 ;; esac
  echo "Removing the leftover DNS records of ${DOMAIN} by hand:"
  aws route53 change-resource-record-sets --hosted-zone-id "$zone" --change-batch "$batch" \
    --query "ChangeInfo.Status" --output text || echo "(could not remove them; remove them in the Route 53 console)"
}

echo "== Remove stale DNS records from an earlier lab (only while no load balancer exists yet) =="
CURRENT_ALB=$(kubectl -n bako get ingress bako -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
if [ -z "$CURRENT_ALB" ]; then
  purge_dns_records
else
  echo "A load balancer already exists (${CURRENT_ALB}); the records are live, leaving them alone."
fi

echo "== Restart the ALB controller so its webhook certificate matches (a repeated bootstrap makes a new one) =="
kubectl -n kube-system rollout restart deployment/aws-load-balancer-controller
kubectl -n kube-system rollout status deployment/aws-load-balancer-controller --timeout=180s
sleep 15

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
echo "== ExternalDNS installed. Chart version (write it into EXTERNALDNS_CHART_VERSION to pin it): =="
helm get metadata external-dns -n kube-system 2>/dev/null | grep -E '^(CHART|VERSION)' || helm list -n kube-system | grep external-dns || true

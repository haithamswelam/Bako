#!/usr/bin/env bash
# pre-destroy-alb.sh - removes the load balancer that the cluster created, BEFORE terraform destroys the cluster.
#
# Why: the ALB is not in terraform. The AWS Load Balancer Controller creates it from K8s/ingress.yaml. If the cluster
# is destroyed first, nobody is left to delete the ALB: it keeps billing every hour and blocks the VPC from being deleted.
#
# What it does:
#   1. Asks AWS if a load balancer (or security group) tagged for this cluster exists. None: nothing to do.
#   2. Pauses Argo CD auto-sync for the app (otherwise it would re-create the Ingress seconds after we delete it).
#   3. Deletes the Ingress objects, so the controller removes the ALB and its security groups.
#   4. Waits until AWS shows none of them left.
#   5. Waits (up to DNS_WAIT_SECONDS) for ExternalDNS to remove the bako.awsbako.site records from Route 53. Those are free,
#      so a leftover is only a warning: the next Start reuses them.
# Exit codes: 0 = nothing left (safe to destroy)   1 = something is still there (do NOT destroy)   2 = could not ask AWS
#
# Settings come from the environment, with these defaults:
set -uo pipefail
unset KUBECONFIG
CLUSTER_NAME="${CLUSTER_NAME:-bako-eks}"
REGION="${REGION:-eu-north-1}"
APP_NAMESPACE="${APP_NAMESPACE:-bako}"          # namespace that holds the Ingress
ARGO_NAMESPACE="${ARGO_NAMESPACE:-argocd}"
ARGO_APP="${ARGO_APP:-bako}"                    # the Argo CD Application to pause
DOMAIN="${DOMAIN:-bako.awsbako.site}"
DNS_WAIT_SECONDS="${DNS_WAIT_SECONDS:-120}"
WAIT_SECONDS="${WAIT_SECONDS:-300}"
POLL_SECONDS="${POLL_SECONDS:-10}"

# The controller puts this tag on everything it creates for the cluster.
list_albs() {
  aws resourcegroupstaggingapi get-resources --region "$REGION" \
    --resource-type-filters elasticloadbalancing:loadbalancer \
    --tag-filters "Key=elbv2.k8s.aws/cluster,Values=${CLUSTER_NAME}" \
    --query "ResourceTagMappingList[].ResourceARN" --output text
}
list_sgs() {
  aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=tag:elbv2.k8s.aws/cluster,Values=${CLUSTER_NAME}" \
    --query "SecurityGroups[].GroupId" --output text
}

# Both lists in one string. Returns 2 if AWS cannot be asked (never "empty" by mistake).
leftovers() {
  local a s
  a=$(list_albs) || return 2
  s=$(list_sgs) || return 2
  echo "${a} ${s}" | xargs
}

# Records ExternalDNS made for the domain (A/AAAA/TXT at the domain name; the certificate CNAME and NS/SOA are not touched).
dns_records() {
  local zone
  zone=$(aws route53 list-hosted-zones-by-name --dns-name "$DOMAIN" --max-items 1 \
    --query "HostedZones[?Name=='${DOMAIN}.'].Id | [0]" --output text 2>/dev/null) || return 2
  [ -z "$zone" ] || [ "$zone" = "None" ] && return 0
  aws route53 list-resource-record-sets --hosted-zone-id "$zone" \
    --query "ResourceRecordSets[?(Type=='A' || Type=='AAAA' || Type=='TXT') && contains(Name, '${DOMAIN}')].[Type,Name]" \
    --output text 2>/dev/null | xargs
}

# Never blocks the destroy: a leftover record costs nothing and the next Start takes it over (same owner id).
wait_for_dns() {
  local w=0 left
  echo "== Waiting up to ${DNS_WAIT_SECONDS}s for ExternalDNS to remove the DNS records of ${DOMAIN} =="
  while true; do
    left=$(dns_records) || { echo "(could not read Route 53; skipping the DNS check)"; return 0; }
    if [ -z "$left" ]; then echo "DNS records removed."; return 0; fi
    if [ "$w" -ge "$DNS_WAIT_SECONDS" ]; then
      echo "WARNING: DNS records still present: $left"
      echo "         They are free and the next Start reuses them. Continuing."
      return 0
    fi
    sleep "$POLL_SECONDS"; w=$((w + POLL_SECONDS))
  done
}

echo "== Checking AWS for load balancers of cluster ${CLUSTER_NAME} in ${REGION} =="
found=$(leftovers); rc=$?
if [ $rc -ne 0 ]; then
  echo "ERROR: could not ask AWS (check the login and the profile). Not safe to destroy." >&2
  exit 2
fi
if [ -z "$found" ]; then
  echo "Nothing to release: no load balancer or controller security group exists for ${CLUSTER_NAME}."
  exit 0
fi
echo "Found: $found"

if ! kubectl --request-timeout=20s get namespace "$APP_NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: AWS still has resources for ${CLUSTER_NAME}, but the cluster cannot be reached, so the controller cannot remove them." >&2
  echo "       Delete the load balancer by hand first (EC2 console > Load Balancers, tag elbv2.k8s.aws/cluster=${CLUSTER_NAME})," >&2
  echo "       and the security groups with the same tag. Then run this script again." >&2
  exit 1
fi

echo "== Pausing Argo CD auto-sync for ${ARGO_APP} (so it does not re-create the Ingress) =="
kubectl -n "$ARGO_NAMESPACE" patch application "$ARGO_APP" --type merge -p '{"spec":{"syncPolicy":{"automated":null}}}' \
  || echo "(Argo application not found or not patched; continuing)"

echo "== Deleting the Ingress objects in ${APP_NAMESPACE} =="
kubectl -n "$APP_NAMESPACE" delete ingress --all --wait=true --timeout=300s || echo "(delete reported a problem; checking AWS anyway)"

echo "== Waiting up to ${WAIT_SECONDS}s for AWS to show nothing left =="
waited=0
while true; do
  found=$(leftovers); rc=$?
  if [ $rc -ne 0 ]; then
    echo "ERROR: could not ask AWS while waiting. Not safe to destroy." >&2
    exit 2
  fi
  if [ -z "$found" ]; then
    echo "The load balancer and its security groups are gone."
    wait_for_dns
    echo "Done. Safe to destroy."
    exit 0
  fi
  if [ "$waited" -ge "$WAIT_SECONDS" ]; then
    echo "ERROR: still present after ${WAIT_SECONDS}s: $found" >&2
    echo "       Do NOT destroy yet. Check: kubectl -n kube-system logs deployment/aws-load-balancer-controller --tail=50" >&2
    exit 1
  fi
  sleep "$POLL_SECONDS"
  waited=$((waited + POLL_SECONDS))
done

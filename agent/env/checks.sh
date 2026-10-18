#!/usr/bin/env bash
# agent/env/checks.sh — plain checks, no LLM.
# Usage: bash agent/env/checks.sh account | nothing-running

set -uo pipefail   # no "-e" on purpose: run ALL checks and report, don't stop at the first failure

EXPECTED_ACCOUNT="483272865934"
###EXPECTED_ACCOUNT="123456789012"
REGION="eu-north-1"
PROFILE="bakolab"
FAILS=0

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAILS=$((FAILS+1)); }

check_account() {
  local acct
  acct=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text 2>/dev/null)
  if [[ "$acct" == "$EXPECTED_ACCOUNT" ]]; then
    pass "AWS account is $EXPECTED_ACCOUNT"
    return 0
  else
    fail "AWS account is '${acct:-unknown}', expected $EXPECTED_ACCOUNT"
    return 1
  fi
}

count_check() {    # usage: count_check "label" "number"
  if [[ "$2" == "0" ]]; then pass "$1: 0"; else fail "$1: $2 (expected 0)"; fi
}

aws_count() {      # usage: aws_count "label" <aws arguments ending with --query 'length(...)'>
  local label="$1"; shift
  local n
  n=$(aws "$@" --region "$REGION" --profile "$PROFILE" --output text 2>/dev/null) || n="ERROR"
  count_check "$label" "$n"
}

check_nothing_running() {
  aws_count "EKS clusters"     eks list-clusters --query 'length(clusters)'
  aws_count "EC2 instances"    ec2 describe-instances --filters Name=instance-state-name,Values=pending,running,stopping,stopped --query 'length(Reservations[].Instances[])'
  aws_count "NAT gateways"     ec2 describe-nat-gateways --filter Name=state,Values=pending,available --query 'length(NatGateways)'
  aws_count "Elastic IPs"      ec2 describe-addresses --query 'length(Addresses)'
  aws_count "RDS instances"    rds describe-db-instances --query 'length(DBInstances)'
  aws_count "Load balancers"   elbv2 describe-load-balancers --query 'length(LoadBalancers)'
  aws_count "EBS volumes"      ec2 describe-volumes --query 'length(Volumes)'
  aws_count "ECR repositories" ecr describe-repositories --query 'length(repositories)'
  aws_count "Secrets"          secretsmanager list-secrets --query 'length(SecretList)'
}

check_context() {
  local ctx
  ctx=$(kubectl config current-context 2>/dev/null)
  if [[ "$ctx" == *"${EXPECTED_ACCOUNT}:cluster/bako-eks" ]]; then
    pass "kubectl context is bako-eks ($EXPECTED_ACCOUNT)"
    return 0
  else
    fail "kubectl context is '${ctx:-none}', expected one ending in ${EXPECTED_ACCOUNT}:cluster/bako-eks"
    return 1
  fi
}

check_argo() {
  local state
  state=$(kubectl get application bako -n argocd \
    -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null) || state="ERROR"
  if [[ "$state" == "Synced/Healthy" ]]; then
    pass "Argo CD app bako: Synced/Healthy"
  else
    fail "Argo CD app bako: $state (expected Synced/Healthy)"
  fi
}

check_pods() {
  local out bad app ok=1
  out=$(kubectl get pods -n bako --no-headers 2>/dev/null) || out=""
  for app in bako-backend bako-frontend; do
    if ! echo "$out" | grep -q "^$app-"; then fail "no pod found for $app"; ok=0; fi
  done
  bad=$(echo "$out" | awk 'NF { split($2,r,"/"); if ($3!="Running" || $4!="0" || r[1]!=r[2]) print $1 }')
  if [[ -n "$bad" ]]; then fail "pods not ready or restarted: $(echo $bad | tr '\n' ' ')"; ok=0; fi
  if [[ $ok -eq 1 ]]; then pass "backend and frontend pods Running, ready, 0 restarts"; fi
}

## READY check: the image tag each Deployment is RUNNING must exist in ECR.
## Reads the tag from the cluster, not from local files, so the branch you are on does not matter.
check_image_tags() {
  local app repo image tag
  for app in backend frontend; do
    repo="bako-${app}"
    image=$(kubectl -n bako get deploy "bako-${app}" \
      -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
    if [ -z "$image" ]; then
      fail "${repo}: deployment not found in cluster"
      continue
    fi
    tag="${image##*:}"
    if aws ecr describe-images --repository-name "$repo" --image-ids imageTag="$tag" \
         --region "$REGION" --profile "$PROFILE" >/dev/null 2>&1; then
      pass "${repo}:${tag} (running in cluster) exists in ECR"
    else
      fail "${repo}:${tag} (running in cluster) NOT found in ECR"
    fi
  done
}

case "${1:-}" in
  account)         check_account ;;
  nothing-running) check_account && check_nothing-running ;;
  ready)           check_account && check_context && { check_image_tags; check_argo; check_pods; } ;;
  nothing-running) check_account && check_nothing-running ;;
  *) echo "usage: $0 account | ready | nothing-running"; exit 2 ;;
esac

echo "----"
if [[ $FAILS -eq 0 ]]; then echo "ALL CHECKS PASSED"; else echo "$FAILS CHECK(S) FAILED"; fi
exit $(( FAILS > 0 ))
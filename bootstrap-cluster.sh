#!/usr/bin/env bash
set -euo pipefail
# Always use the default kubeconfig (~/.kube/config), never a leftover KUBECONFIG
# from the calling shell (e.g. one pointing at the local k3d cluster)
unset KUBECONFIG

# --- Config: adjust if your cluster/region/role names ever change ---
# Each value can also be set from the environment, for example: CLUSTER_NAME=other-eks ./bootstrap-cluster.sh
CLUSTER_NAME="${CLUSTER_NAME:-bako-eks}"
REGION="${REGION:-eu-north-1}"
ESO_ROLE_ARN="${ESO_ROLE_ARN:-arn:aws:iam::483272865934:role/bako-external-secrets-irsa-role}"
# AWS Load Balancer Controller: the IAM role is looked up by name (terraform creates it), so no account id is typed here.
# ALB_CHART_VERSION must match the policy file infra-Bako-eks/iam-policies/aws-load-balancer-controller-v<version>.json
ALB_ROLE_NAME="${ALB_ROLE_NAME:-bako-alb-controller-irsa-role}"
ALB_CHART_VERSION="${ALB_CHART_VERSION:-3.6.2}"

echo "== 1. Point kubectl at the (freshly terraform-applied) cluster =="
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"

EXPECTED_ACCOUNT="${EXPECTED_ACCOUNT:-483272865934}"
CURRENT_CONTEXT=$(kubectl config current-context)
if [[ "$CURRENT_CONTEXT" != *"${EXPECTED_ACCOUNT}:cluster/${CLUSTER_NAME}" ]]; then
  echo "ERROR: kubectl context is '$CURRENT_CONTEXT', expected account ${EXPECTED_ACCOUNT} cluster ${CLUSTER_NAME}. Aborting." >&2
  exit 1
fi

echo "== 2. Register/refresh Helm chart repos =="
helm repo add external-secrets https://charts.external-secrets.io
helm repo add argo https://argoproj.github.io/argo-helm
helm repo add eks https://aws.github.io/eks-charts
helm repo update

echo "== 3. Install/upgrade External Secrets Operator, with IRSA annotation =="
helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace external-secrets \
  --create-namespace \
  --set installCRDs=true \
  --set serviceAccount.name=external-secrets \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"="$ESO_ROLE_ARN" \
  --wait

echo "== 3b. Install/upgrade the AWS Load Balancer Controller (turns the Ingress into an ALB) =="
# It must be ready BEFORE Argo CD applies K8s/ingress.yaml, so it is installed first.
FOUND_CHART=$(helm search repo eks/aws-load-balancer-controller --version "$ALB_CHART_VERSION" || true)
if ! grep -q aws-load-balancer-controller <<<"$FOUND_CHART"; then
  echo "ERROR: chart version ${ALB_CHART_VERSION} of eks/aws-load-balancer-controller was not found." >&2
  echo "       See what exists with:  helm search repo eks/aws-load-balancer-controller --versions | head" >&2
  echo "       Then set ALB_CHART_VERSION here and use the matching policy file in infra-Bako-eks/iam-policies/." >&2
  exit 1
fi
VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" --query "cluster.resourcesVpcConfig.vpcId" --output text)
ALB_ROLE_ARN=$(aws iam get-role --role-name "$ALB_ROLE_NAME" --query "Role.Arn" --output text)
# region and vpcId are given explicitly so the controller does not have to ask the node metadata service
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system \
  --version "$ALB_CHART_VERSION" \
  --set clusterName="$CLUSTER_NAME" \
  --set region="$REGION" \
  --set vpcId="$VPC_ID" \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"="$ALB_ROLE_ARN" \
  --wait --timeout 5m
kubectl rollout status deployment/aws-load-balancer-controller -n kube-system --timeout=180s

echo "== 4. Install/upgrade Argo CD =="
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --wait

echo "== 5. Wait for argocd-server to actually be ready before registering the Application =="
kubectl rollout status deployment/argocd-server -n argocd --timeout=180s

echo "== 6. Apply the bako Application — this bootstraps everything else: =="
echo "     namespace 'bako', ClusterSecretStore, ExternalSecret, backend+frontend Deployments/Services"
kubectl apply -f argocd/bako-application.yaml

echo "== 7. Print the Argo CD initial admin password for convenience =="
echo -n "Argo CD admin password: "
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
echo
echo
echo "Done. Run: kubectl get applications -n argocd   (watch for Synced/Healthy)"
echo "Then:      kubectl port-forward svc/argocd-server -n argocd 8087:443"
echo "Then open: https://localhost:8087   (user: admin)"
echo
echo
echo " Check Cluster is up and running"
kubectl get pods -n bako
echo
echo "Public address (the ALB takes 2 to 3 minutes to appear, run again if empty):"
echo "   kubectl get ingress bako -n bako"

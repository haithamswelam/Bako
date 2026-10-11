#!/usr/bin/env bash
set -euo pipefail
# Always use the default kubeconfig (~/.kube/config), never a leftover KUBECONFIG
# from the calling shell (e.g. one pointing at the local k3d cluster)
unset KUBECONFIG

# --- Config: adjust if your cluster/region/role names ever change ---
CLUSTER_NAME="bako-eks"
REGION="eu-north-1"
ESO_ROLE_ARN="arn:aws:iam::483272865934:role/bako-external-secrets-irsa-role"

echo "== 1. Point kubectl at the (freshly terraform-applied) cluster =="
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"

EXPECTED_ACCOUNT="483272865934"
CURRENT_CONTEXT=$(kubectl config current-context)
if [[ "$CURRENT_CONTEXT" != *"${EXPECTED_ACCOUNT}:cluster/${CLUSTER_NAME}" ]]; then
  echo "ERROR: kubectl context is '$CURRENT_CONTEXT', expected account ${EXPECTED_ACCOUNT} cluster ${CLUSTER_NAME}. Aborting." >&2
  exit 1
fi

echo "== 2. Register/refresh Helm chart repos =="
helm repo add external-secrets https://charts.external-secrets.io
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

echo "== 3. Install/upgrade External Secrets Operator, with IRSA annotation =="
helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace external-secrets \
  --create-namespace \
  --set installCRDs=true \
  --set serviceAccount.name=external-secrets \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"="$ESO_ROLE_ARN" \
  --wait

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
echo "Then:      kubectl port-forward svc/argocd-server -n argocd 8081:443"
echo
echo
echo " Check Cluster is up and running"
kubectl get pods -n bako

# IAM for the AWS Load Balancer Controller (IRSA, the same pattern as eso-irsa.tf).
# The controller runs in the cluster, watches Ingress objects, and creates the ALB, its listeners,
# target groups and security groups in AWS. It needs permission to do that, and only it gets it:
# the trust policy below accepts exactly one Kubernetes service account.
#
# Reuses local.eks_oidc_provider_url, which is defined in eso-irsa.tf.

locals {
  alb_controller_subject = "system:serviceaccount:${var.alb_controller_namespace}:${var.alb_controller_service_account}"
}

# The official policy of the controller, pinned to the same version that bootstrap-cluster.sh installs.
# To upgrade the controller: download that version's docs/install/iam_policy.json, save it here under a new name,
# change the file name below, and change ALB_CHART_VERSION in bootstrap-cluster.sh.
resource "aws_iam_policy" "alb_controller" {
  name        = "bako-alb-controller-policy"
  description = "AWS Load Balancer Controller v3.6.2: lets the controller manage ALBs for the bako cluster"
  policy      = file("${path.module}/iam-policies/aws-load-balancer-controller-v3.6.2.json")
}

resource "aws_iam_role" "alb_controller" {
  name = "bako-alb-controller-irsa-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.eks.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${local.eks_oidc_provider_url}:sub" = local.alb_controller_subject
            "${local.eks_oidc_provider_url}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "alb_controller" {
  role       = aws_iam_role.alb_controller.name
  policy_arn = aws_iam_policy.alb_controller.arn
}

output "alb_controller_role_arn" {
  value = aws_iam_role.alb_controller.arn
}

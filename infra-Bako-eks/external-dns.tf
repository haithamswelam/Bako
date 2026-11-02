# IAM for ExternalDNS (IRSA, the same pattern as alb-controller.tf).
# ExternalDNS is a pod in the cluster. After each START it reads the Ingress, sees the new ALB address, and writes the
# DNS record bako.awsbako.site -> that ALB into Route 53. It may change records in ONE zone only, and only it gets this role.
#
# Needs the zone to exist already: it is created once by infra-Bako-persistent (README-https-step2.txt, steps A to D).
# Reuses local.eks_oidc_provider_url and aws_iam_openid_connect_provider.eks, defined in eso-irsa.tf.

variable "bako_domain_name" {
  type        = string
  default     = "bako.awsbako.site"
  description = "The subdomain managed in Route 53 (the zone made by infra-Bako-persistent)."
}

data "aws_route53_zone" "bako" {
  name         = var.bako_domain_name
  private_zone = false
}

locals {
  external_dns_subject = "system:serviceaccount:kube-system:external-dns"
}

resource "aws_iam_policy" "external_dns" {
  name        = "bako-external-dns-policy"
  description = "ExternalDNS: may change records in the ${var.bako_domain_name} zone only"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["route53:ChangeResourceRecordSets"]
        Resource = ["arn:aws:route53:::hostedzone/${data.aws_route53_zone.bako.zone_id}"]
      },
      {
        Effect   = "Allow"
        Action   = ["route53:ListHostedZones", "route53:ListResourceRecordSets", "route53:ListTagsForResource"]
        Resource = ["*"]
      }
    ]
  })
}

resource "aws_iam_role" "external_dns" {
  name = "bako-external-dns-irsa-role"

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
            "${local.eks_oidc_provider_url}:sub" = local.external_dns_subject
            "${local.eks_oidc_provider_url}:aud" = "sts.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "external_dns" {
  role       = aws_iam_role.external_dns.name
  policy_arn = aws_iam_policy.external_dns.arn
}

output "external_dns_role_arn" {
  value = aws_iam_role.external_dns.arn
}
